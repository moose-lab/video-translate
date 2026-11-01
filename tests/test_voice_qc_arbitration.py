"""Durable same-paid-identity arbitration across cancellation and ready checkpoints."""

# ruff: noqa: F811
import os
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import uuid4

import pytest
from dubbing_helpers import guard, make_track
from sqlalchemy import select
from test_submission_receipts import receipt_project  # noqa: F401
from test_synthesis_domain import body, path, synthesis_project  # noqa: F401
from test_synthesis_operations import history
from test_translation_operations import drain
from test_voice_qc_operations import detail, edit_target, enqueue, prepared, qc_body
from test_voice_qc_review_fixes import force_due


@pytest.fixture
def pg_synthesis_factory(client_factory, register, tmp_path, monkeypatch):
    import psycopg
    from dubbing_helpers import make_probed_project
    from psycopg import sql
    from sqlalchemy import MetaData
    from test_synthesis_domain import prepare_synthesis

    from videotranslate.db import Base

    owned = []

    def create():
        admin_url = os.environ.get("VT_TEST_POSTGRES_ADMIN_URL")
        if not admin_url:
            pytest.skip("Opt-in isolated PostgreSQL unavailable")
        admin = psycopg.connect(admin_url, autocommit=True)
        name = "voice_qc_arbitration_" + uuid4().hex
        admin.execute(sql.SQL("CREATE DATABASE {} OWNER vt_test").format(sql.Identifier(name)))
        item = [admin, name, None]
        owned.append(item)
        url = (admin_url.rsplit("/", 1)[0] + "/" + name).replace(
            "postgresql://", "postgresql+psycopg://"
        )

        def schema(bind):
            metadata = MetaData()
            for table in Base.metadata.tables.values():
                table.to_metadata(metadata)
            metadata.create_all(bind)

        monkeypatch.setattr(Base.metadata, "create_all", schema)
        media_root = tmp_path / "arbitration-pg"
        media_root.mkdir()
        fixture = make_probed_project(
            lambda: client_factory(database_url=url), register, media_root
        )
        item[2] = fixture[0]
        return prepare_synthesis(fixture)

    yield create
    for admin, name, client in owned:
        if client:
            client.close()
            client.app.state.engine.dispose()
        admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))
        admin.close()


def japanese(f):
    c, h, p, s, line, *_ = f
    make_track(c, h, f"/api/projects/{p['id']}", "ja")
    ja = path(f).replace("zh-Hant", "ja")
    assert (
        c.patch(
            ja + f"/segments/{line['id']}",
            headers=h,
            json=guard(s, line["transcript_revision"])
            | {
                "revision": 0,
                "expected_source_text_fingerprint": line["source_text_fingerprint"],
                "text": "別のターゲット",
                "approved": True,
            },
        ).status_code
        == 200
    )
    assert c.post(ja + "/synthesize", headers=h, json=body(f)).status_code == 202
    drain(c)
    return ja


def queue_japanese(f, ja):
    c, h, *_ = f
    payload = qc_body(f)
    payload["segments"][0]["output_id"] = c.get(
        ja + f"/segments/{f[4]['id']}/audio-history"
    ).json()["selected_output_id"]
    response = c.post(ja + "/voice-qc", headers=h, json=payload)
    assert response.status_code == 202, response.text
    return response.json()


@pytest.mark.parametrize("backend", ["sqlite", "postgresql"])
@pytest.mark.parametrize("checkpoint", ["before_cpu", "ready_real", "interrupted_adoption"])
def test_retried_predecessor_waits_for_preparing_peer_and_adopts_without_io(
    synthesis_project, monkeypatch, tmp_path, checkpoint, backend, pg_synthesis_factory
):
    from videotranslate.execution.contracts import CancellationRequested
    from videotranslate.execution.media_inputs import materialize
    from videotranslate.execution.prepared import Operations
    from videotranslate.execution.worker import Worker
    from videotranslate.models.analysis import PreparedObject, PrivateOperation

    f = pg_synthesis_factory() if backend == "postgresql" else synthesis_project
    http = prepared(f, monkeypatch, tmp_path)
    c, h, *_ = f
    ja = japanese(f)
    first = enqueue(f)
    run_id = first["lines"][0]["run_id"]
    original_begin = Operations.begin
    if checkpoint != "before_cpu":

        def cancel_before_post(*args, **kwargs):
            assert c.post(f"/api/runs/{run_id}/cancel", headers=h, json={}).status_code == 200
            raise CancellationRequested()

        monkeypatch.setattr(Operations, "begin", cancel_before_post)
        assert Worker(c.app.state.settings).run_once()
        monkeypatch.setattr(Operations, "begin", original_begin)
        with c.app.state.session_factory() as db:
            op = db.scalar(select(PrivateOperation).where(PrivateOperation.run_id == run_id))
            assert op.phase == "ready"
            assert db.scalar(select(PreparedObject).where(PreparedObject.operation_id == op.id))
    else:
        assert c.post(f"/api/runs/{run_id}/cancel", headers=h, json={}).status_code == 200
    second = queue_japanese(f, ja)
    entered, release = Event(), Event()
    calls = []

    def paused(context, asset, destination, **kwargs):
        calls.append(asset.id)
        if len(calls) == 1:
            entered.set()
            assert release.wait(15)
        return materialize(context, asset, destination, **kwargs)

    monkeypatch.setattr("videotranslate.execution.media_inputs.materialize", paused)
    with ThreadPoolExecutor(max_workers=2) as pool:
        peer = pool.submit(Worker(c.app.state.settings).run_once)
        try:
            assert entered.wait(5)
            assert c.post(f"/api/runs/{run_id}/retry", headers=h, json={}).status_code == 200
            assert Worker(c.app.state.settings).run_once()
            assert detail(f, first)["lines"][0]["status"] == "retry_wait"
            assert len(calls) == 1 and not http.posts
        finally:
            release.set()
        assert peer.result(timeout=5)
    assert len(http.posts) == 1

    def forbidden(*args, **kwargs):
        raise AssertionError("local adoption must not materialize/decrypt/construct HTTP")

    monkeypatch.setattr("videotranslate.execution.media_inputs.materialize", forbidden)
    monkeypatch.setattr("videotranslate.execution.provider_runtime.credential_token", forbidden)
    monkeypatch.setattr("videotranslate.dubbing.remote_voice_qc.make_http", forbidden)
    original_cache = Operations.cache
    if checkpoint == "interrupted_adoption":

        def interrupt(self, payload, facts):
            if facts.get("reused"):
                raise RuntimeError("lost process after real-ready became pinned alias")
            return original_cache(self, payload, facts)

        monkeypatch.setattr(Operations, "cache", interrupt)
    force_due(c, run_id)
    assert Worker(c.app.state.settings).run_once()
    if checkpoint == "interrupted_adoption":
        assert detail(f, first)["lines"][0]["status"] == "failed"
        with c.app.state.session_factory() as db:
            op = db.scalar(select(PrivateOperation).where(PrivateOperation.run_id == run_id))
            assert op.phase == "ready" and "reuse_line_id" in op.request_payload
        monkeypatch.setattr(Operations, "cache", original_cache)
        assert c.post(f"/api/runs/{run_id}/retry", headers=h, json={}).status_code == 200
        assert Worker(c.app.state.settings).run_once()
    assert detail(f, first)["lines"][0]["status"] == "succeeded"
    assert c.get(ja + "/voice-qc/" + second["id"]).json()["lines"][0]["status"] == "succeeded"
    assert len(http.posts) == 1 and len(calls) == 1


def test_submission_boundary_adopts_success_that_appeared_after_initial_lookup(
    synthesis_project, monkeypatch, tmp_path
):
    from videotranslate.execution.media_inputs import materialize
    from videotranslate.models.analysis import PrivateOperation

    f = synthesis_project
    http = prepared(f, monkeypatch, tmp_path)
    first = enqueue(f)
    drain(f[0])
    c = f[0]
    run_id = first["lines"][0]["run_id"]
    with c.app.state.session_factory.begin() as db:
        op = db.scalar(select(PrivateOperation).where(PrivateOperation.run_id == run_id))
        op.phase = "ready"  # controlled inconclusive checkpoint, retain actual paid payload
    edit_target(f, "Corrected expected wording")
    second = enqueue(f, target_revision=2)
    calls = []

    def reveal(context, asset, destination, **kwargs):
        calls.append(asset.id)
        with c.app.state.session_factory.begin() as db:
            db.scalar(
                select(PrivateOperation).where(PrivateOperation.run_id == run_id)
            ).phase = "prepared"
        return materialize(context, asset, destination, **kwargs)

    monkeypatch.setattr("videotranslate.execution.media_inputs.materialize", reveal)
    drain(c)
    assert detail(f, second)["lines"][0]["status"] == "succeeded"
    assert len(http.posts) == 1 and len(calls) == 1
    assert history(f)["outputs"][0]["stale"]


def test_distinct_verification_identity_remains_independent_during_preparation(
    synthesis_project, monkeypatch, tmp_path
):
    from test_voice_qc_review_fixes import configure

    from videotranslate.execution.media_inputs import materialize
    from videotranslate.execution.worker import Worker

    f = synthesis_project
    http = prepared(f, monkeypatch, tmp_path)
    c = f[0]
    ja = japanese(f)
    first = enqueue(f)
    configure(f, 1)
    second = queue_japanese(f, ja)
    entered, release = Event(), Event()
    calls = []

    def pause(context, asset, destination, **kwargs):
        calls.append(asset.id)
        if len(calls) == 1:
            entered.set()
            assert release.wait(15)
        return materialize(context, asset, destination, **kwargs)

    monkeypatch.setattr("videotranslate.execution.media_inputs.materialize", pause)
    with ThreadPoolExecutor(max_workers=2) as pool:
        earlier = pool.submit(Worker(c.app.state.settings).run_once)
        try:
            assert entered.wait(5)
            assert Worker(c.app.state.settings).run_once()
            assert len(http.posts) == 1
            assert (
                c.get(ja + "/voice-qc/" + second["id"]).json()["lines"][0]["status"] == "succeeded"
            )
        finally:
            release.set()
        assert earlier.result(timeout=5)
    assert detail(f, first)["lines"][0]["status"] == "succeeded"
    assert len(http.posts) == 2 and len(calls) == 2


@pytest.mark.parametrize("lease_fault", ["expired", "missing_token"])
def test_expired_submitting_peer_requires_reconciliation_instead_of_new_post(
    synthesis_project, monkeypatch, tmp_path, lease_fault
):
    from datetime import timedelta

    from videotranslate.execution.worker import Worker
    from videotranslate.models.core import utcnow
    from videotranslate.models.execution import StageRun

    f = synthesis_project
    http = prepared(f, monkeypatch, tmp_path)
    c, h, *_ = f
    ja = japanese(f)
    first = enqueue(f)
    second = queue_japanese(f, ja)
    entered, release = Event(), Event()

    def hold():
        entered.set()
        assert release.wait(15)

    http.hook = hold
    with ThreadPoolExecutor(max_workers=2) as pool:
        running = pool.submit(Worker(c.app.state.settings).run_once)
        try:
            assert entered.wait(5)
            with c.app.state.session_factory.begin() as db:
                active = db.get(StageRun, first["lines"][0]["run_id"])
                if lease_fault == "missing_token":
                    active.lease_token = None
                else:
                    active.lease_expires_at = utcnow() - timedelta(seconds=1)
            assert Worker(c.app.state.settings).run_once()
            assert len(http.posts) == 1
        finally:
            release.set()
        assert running.result(timeout=5)
    row = c.get(ja + "/voice-qc/" + second["id"]).json()["lines"][0]
    assert row["status"] == "needs_review"
    assert len(http.posts) == 1
    assert (
        c.post(f"/api/runs/{first['lines'][0]['run_id']}/retry", headers=h, json={}).status_code
        == 409
    )


def test_ready_real_adoption_releases_only_unused_preprocessing_orphan(
    synthesis_project, monkeypatch, tmp_path
):
    from datetime import timedelta

    from videotranslate.execution.contracts import CancellationRequested
    from videotranslate.execution.prepared import Operations, cleanup_orphans
    from videotranslate.execution.worker import Worker
    from videotranslate.models.core import Project, utcnow

    f = synthesis_project
    http = prepared(f, monkeypatch, tmp_path)
    c, h, *_ = f
    ja = japanese(f)
    first = enqueue(f)
    run_id = first["lines"][0]["run_id"]
    begin = Operations.begin

    def cancel(*args, **kwargs):
        assert c.post(f"/api/runs/{run_id}/cancel", headers=h, json={}).status_code == 200
        raise CancellationRequested()

    monkeypatch.setattr(Operations, "begin", cancel)
    assert Worker(c.app.state.settings).run_once()
    monkeypatch.setattr(Operations, "begin", begin)
    queue_japanese(f, ja)
    drain(c)
    assert c.post(f"/api/runs/{run_id}/retry", headers=h, json={}).status_code == 200
    drain(c)
    assert detail(f, first)["lines"][0]["status"] == "succeeded"
    with c.app.state.session_factory() as db:
        workspace = db.get(Project, f[2]["id"]).workspace_id
    assert (
        cleanup_orphans(
            c.app.state.session_factory,
            c.app.state.storage,
            workspace_id=workspace,
            before=utcnow() + timedelta(seconds=1),
        )
        == 1
    )
    assert len(http.posts) == 1


@pytest.mark.parametrize("phase", ["submitting", "prepared"])
def test_ready_checkpoint_update_cannot_relabel_paid_or_completed_operation(receipt_project, phase):
    from test_submission_receipts import pending

    from videotranslate.execution.contracts import FailureCode, StageFailure

    _, operations, operation, _ = pending(receipt_project)
    if phase == "prepared":
        operations.cache({"fixture": True}, {"count": 1})
    # Default idempotent prepare remains unchanged for every other stage.
    same = operations.prepare(
        provider="omnivoice", model="OmniVoice", request_payload={"new": True}
    )
    assert same.id == operation.id and same.request_payload == operation.request_payload
    with pytest.raises(StageFailure) as denied:
        operations.prepare(
            provider="omnivoice",
            model="OmniVoice",
            request_payload={"new": True},
            update_ready=True,
        )
    assert denied.value.code == FailureCode.CONFIGURATION and denied.value.review
    assert operations.current().phase == phase

"""Task 4B SPEC regressions. Remote responses are explicit recording doubles."""

from datetime import timedelta

import pytest
from dubbing_helpers import selected
from sqlalchemy import select
from test_analysis_execution import claimed
from test_analysis_workflow import configure_remote, recording_provider, timeline
from test_voice_references import upload, wav_bytes

from videotranslate.execution.context import RunContext
from videotranslate.execution.contracts import RunCreate, StageResult
from videotranslate.execution.prepared import Operations, cleanup_orphans
from videotranslate.execution.registry import STAGES, StageDefinition
from videotranslate.execution.service import claim_run
from videotranslate.execution.worker import Worker
from videotranslate.models.analysis import ReferenceRequest
from videotranslate.models.core import Project, utcnow
from videotranslate.models.execution import ProjectEvent, StageRun


def prepare_extract(fixture, monkeypatch):
    client, headers, p = fixture
    selected(fixture)
    configure_remote(fixture)
    provider = recording_provider(monkeypatch, client)
    base = f"/api/projects/{p['id']}"
    assert (
        client.post(base + "/runs", headers=headers, json={"stage": "extract"}).status_code == 201
    )
    assert Worker(client.app.state.settings).run_once()
    return base, provider


def test_distinct_request_keys_share_paid_media_and_each_key_keeps_its_conflict_binding(
    dubbing_project, monkeypatch
):
    client, headers, p = dubbing_project
    base, provider = prepare_extract(dubbing_project, monkeypatch)
    first = client.post(
        base + "/runs", headers=headers | {"Idempotency-Key": "key-A"}, json={"stage": "separate"}
    )
    second = client.post(
        base + "/runs", headers=headers | {"Idempotency-Key": "key-B"}, json={"stage": "separate"}
    )
    assert first.status_code == second.status_code == 201
    assert first.json()["id"] == second.json()["id"]
    assert Worker(client.app.state.settings).run_once()
    assert len(provider.posts) == 1
    assert not Worker(client.app.state.settings).run_once()
    # A fresh key after successful publication also shares the same paid result.
    third = client.post(
        base + "/runs", headers=headers | {"Idempotency-Key": "key-C"}, json={"stage": "separate"}
    )
    assert third.json()["id"] == first.json()["id"]
    # Every alias remembers its own original request; returning a shared ID alone is insufficient.
    for key in ("key-A", "key-B", "key-C"):
        conflict = client.post(
            base + "/runs", headers=headers | {"Idempotency-Key": key}, json={"stage": "probe"}
        )
        assert (
            conflict.status_code == 409
            and conflict.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"
        )
    # The same alias also rejects an equivalent stage after its actual inputs change.
    current = client.get(base).json()
    assert (
        client.put(
            base + "/source-selection",
            headers=headers,
            json={
                "revision": current["revision"],
                "source_asset_id": p["source_asset_id"],
                "audio_ordinal": 0,
                "start_ms": 200,
                "end_ms": 1200,
            },
        ).status_code
        == 200
    )
    assert (
        client.post(base + "/runs", headers=headers, json={"stage": "extract"}).status_code == 201
    )
    assert Worker(client.app.state.settings).run_once()
    conflict = client.post(
        base + "/runs", headers=headers | {"Idempotency-Key": "key-B"}, json={"stage": "separate"}
    )
    assert (
        conflict.status_code == 409 and conflict.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"
    )
    assert len(provider.posts) == 1


def test_keyed_failed_accepted_media_is_shared_by_other_key_and_workflow(
    dubbing_project, monkeypatch
):
    from videotranslate.providers.contracts import ProviderError

    client, headers, _ = dubbing_project
    base, provider = prepare_extract(dubbing_project, monkeypatch)

    def denied(self, url, **kw):
        raise ProviderError("auth")

    monkeypatch.setattr(provider, "get_sse", denied)
    first = client.post(
        base + "/runs",
        headers=headers | {"Idempotency-Key": "accepted-A"},
        json={"stage": "separate"},
    ).json()
    assert Worker(client.app.state.settings).run_once()
    assert client.get("/api/runs/" + first["id"]).json()["status"] == "failed"
    second = client.post(
        base + "/runs",
        headers=headers | {"Idempotency-Key": "accepted-B"},
        json={"stage": "separate"},
    )
    assert second.json()["id"] == first["id"] and second.json()["remote_id"] == "actual-remote-id"
    workflow = client.post(
        base + "/workflow",
        headers=headers,
        json={
            "action": "prepare_media",
            "expected_editor_fingerprint": timeline(dubbing_project)["editor_fingerprint"],
        },
    )
    assert workflow.status_code == 202 and workflow.json()["status"] == "failed"
    assert not Worker(client.app.state.settings).run_once()
    assert len(provider.posts) == 1


@pytest.mark.parametrize("kind", ["sync", "async", "terminal_files"])
def test_reclaim_reports_actual_cached_recovery_without_resubmission(execution_project, kind):
    client, _, project = execution_project
    ctx = claimed(client, project)
    operations = Operations(ctx)
    operation = operations.prepare(
        provider="hf_router" if kind == "sync" else "demucs",
        model="test/model",
        connection_revision=1,
        host="https://recording.hf.space",
        prefix="/gradio_api",
    )
    operations.begin()
    if kind != "sync":
        operations.accept("recorded-job")
    if kind == "terminal_files":
        operations.terminal(
            {"vocals": {"path": "/tmp/v.wav"}, "instrumental": {"path": "/tmp/i.wav"}}
        )
    else:
        operations.cache({"segments": []}, {"segment_count": 0})
    with ctx.session_factory.begin() as db:
        db.get(StageRun, ctx.run_id).lease_expires_at = utcnow() - timedelta(seconds=1)
    seen = []
    definition = STAGES["probe"]

    def cached_handler(restarted):
        store = Operations(restarted)
        saved = store.current()
        assert saved.id == operation.id
        seen.append(saved.phase)
        if kind == "terminal_files":
            assert saved.terminal_payload["vocals"]["path"] == "/tmp/v.wav"
            return store.cache({"objects": []}, {"object_count": 0})
        return store.cached()

    registry = {
        "probe": StageDefinition(
            "probe", definition.validate_options, definition.resolve_inputs, cached_handler
        )
    }
    assert Worker(ctx.settings, registry=registry).run_once()
    with ctx.session_factory() as db:
        events = db.scalars(
            select(ProjectEvent).where(
                ProjectEvent.run_id == ctx.run_id, ProjectEvent.kind == "run.recovery"
            )
        ).all()
        assert len(events) == 1
        assert events[0].facts["recovery"] == (
            "resume_download" if kind == "terminal_files" else "reuse_prepared"
        )
    assert seen == ["terminal" if kind == "terminal_files" else "prepared"]


def failed_partial_upload(fixture, monkeypatch):
    client, _, p = fixture
    storage = client.app.state.storage
    original = storage.put

    def partial(key, source, content_type):
        original(key, source, content_type)
        raise OSError("test-only interrupted store")

    monkeypatch.setattr(storage, "put", partial)
    response = upload(fixture)
    assert response.status_code == 503
    with client.app.state.session_factory() as db:
        record = db.scalar(select(ReferenceRequest).where(ReferenceRequest.project_id == p["id"]))
        assert record.run_id is None and record.upload_state == "orphan"
    with storage.open(record.upload_key) as stream:
        assert stream.read() == wav_bytes()
    return record


def gc(client, workspace):
    return cleanup_orphans(
        client.app.state.session_factory,
        client.app.state.storage,
        workspace_id=workspace,
        before=utcnow() + timedelta(days=1),
    )


def test_raw_partial_upload_has_owned_retryable_cleanup_outside_transaction(
    dubbing_project, monkeypatch
):
    from sqlalchemy import update

    client, _, _ = dubbing_project
    record = failed_partial_upload(dubbing_project, monkeypatch)
    storage = client.app.state.storage
    original = storage.delete
    deletes = []

    def delete(key):
        # An independent write can complete while storage deletion runs.
        with client.app.state.session_factory.begin() as db:
            db.execute(
                update(Project)
                .where(Project.id == record.project_id)
                .values(event_sequence=Project.event_sequence)
            )
        deletes.append(key)
        if len(deletes) == 1:
            raise OSError("test-only failed delete")
        original(key)

    monkeypatch.setattr(storage, "delete", delete)
    assert gc(client, "another-workspace") == 0
    assert gc(client, record.workspace_id) == 0
    with client.app.state.session_factory() as db:
        assert db.get(ReferenceRequest, record.id).upload_state == "deleting"
    assert gc(client, record.workspace_id) == 1
    assert deletes == [record.upload_key, record.upload_key]
    with client.app.state.session_factory() as db:
        assert db.get(ReferenceRequest, record.id).upload_state == "deleted"
    with pytest.raises(FileNotFoundError):
        storage.open(record.upload_key)


def test_raw_writing_reservation_is_protected_until_upload_lease_expires(
    dubbing_project, monkeypatch
):
    client, _, _ = dubbing_project
    record = failed_partial_upload(dubbing_project, monkeypatch)
    with client.app.state.session_factory.begin() as db:
        row = db.get(ReferenceRequest, record.id)
        row.upload_state = "writing"
        row.upload_lease_expires_at = utcnow() + timedelta(hours=1)
    assert gc(client, record.workspace_id) == 0
    with client.app.state.session_factory.begin() as db:
        db.get(ReferenceRequest, record.id).upload_lease_expires_at = utcnow() - timedelta(
            seconds=1
        )
    assert gc(client, record.workspace_id) == 1


def test_invalid_raw_reference_can_be_collected_and_cannot_be_retried_without_upload(
    dubbing_project,
):
    client, headers, p = dubbing_project
    response = upload(dubbing_project, b"not audio")
    assert response.status_code == 202
    assert Worker(client.app.state.settings).run_once()
    with client.app.state.session_factory() as db:
        record = db.scalar(select(ReferenceRequest).where(ReferenceRequest.project_id == p["id"]))
    assert gc(client, record.workspace_id) == 1
    retry = client.post(
        "/api/runs/" + response.json()["run"]["id"] + "/retry", headers=headers, json={}
    )
    assert retry.status_code == 409 and retry.json()["error"]["code"] == "INPUT_REQUIRED"
    with pytest.raises(FileNotFoundError):
        client.app.state.storage.open(record.upload_key)


def test_raw_queued_expired_worker_cache_and_published_history_remain_protected(dubbing_project):
    from videotranslate.dubbing.references import reference_handler

    client, headers, p = dubbing_project
    response = upload(dubbing_project)
    assert response.status_code == 202
    with client.app.state.session_factory() as db:
        record = db.scalar(select(ReferenceRequest).where(ReferenceRequest.project_id == p["id"]))
    assert gc(client, record.workspace_id) == 0
    with client.app.state.session_factory.begin() as db:
        lease = claim_run(db, "reference-worker")
        lease.lease_expires_at = utcnow() - timedelta(seconds=1)
    assert gc(client, record.workspace_id) == 0  # recoverable CPU input, not an orphan output
    with client.app.state.session_factory.begin() as db:
        lease = claim_run(db, "recovered-worker")
    ctx = RunContext(
        client.app.state.session_factory,
        client.app.state.storage,
        client.app.state.settings,
        lease.id,
        lease.lease_token,
    )
    result = reference_handler(ctx)
    assert isinstance(result, StageResult)
    with client.app.state.session_factory.begin() as db:
        run = db.get(StageRun, lease.id)
        run.status, run.lease_token, run.lease_expires_at = "failed", None, None
    assert gc(client, record.workspace_id) == 0  # prepared success awaiting publication
    assert (
        client.post("/api/runs/" + lease.id + "/retry", headers=headers, json={}).status_code == 200
    )
    assert Worker(client.app.state.settings).run_once()
    refs = client.get(f"/api/projects/{p['id']}/references").json()["items"]
    assert len(refs) == 1
    assert (
        client.post(
            f"/api/projects/{p['id']}/references/{refs[0]['reference_id']}/versions",
            headers=headers,
            json={
                "parent_version_id": refs[0]["id"],
                "text": "Historical revision",
                "language": "en",
            },
        ).status_code
        == 201
    )
    with client.app.state.session_factory.begin() as db:
        db.get(ReferenceRequest, record.id).upload_state = "orphan"
        db.get(StageRun, lease.id).request_key = None
    assert gc(client, record.workspace_id) == 0  # historical reference still owns this original
    with client.app.state.storage.open(record.upload_key) as stream:
        assert stream.read() == wav_bytes()


@pytest.mark.parametrize("order", ["delete_first", "writer_first"])
def test_expired_upload_writer_is_fenced_and_late_bytes_are_recleaned(
    dubbing_project, monkeypatch, order
):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    client, _, p = dubbing_project
    storage = client.app.state.storage
    put_started, put_release = Event(), Event()
    delete_started, delete_release = Event(), Event()
    original_put, original_delete = storage.put, storage.delete
    deletes = []

    def deferred_put(key, source, content_type):
        put_started.set()
        assert put_release.wait(10)
        original_put(key, source, content_type)

    def deferred_delete(key):
        deletes.append(key)
        delete_started.set()
        if order == "writer_first":
            assert delete_release.wait(10)
        original_delete(key)

    monkeypatch.setattr(storage, "put", deferred_put)
    monkeypatch.setattr(storage, "delete", deferred_delete)
    with ThreadPoolExecutor(2) as pool:
        pending_upload = pool.submit(upload, dubbing_project)
        try:
            assert put_started.wait(5)
            with client.app.state.session_factory.begin() as db:
                record = db.scalar(
                    select(ReferenceRequest).where(ReferenceRequest.project_id == p["id"])
                )
                record.upload_lease_expires_at = utcnow() - timedelta(seconds=1)
            if order == "delete_first":
                assert gc(client, record.workspace_id) == 1
                # Until the old writer settles, keep a tombstone capable of re-deletion.
                assert gc(client, record.workspace_id) == 0
                assert len(deletes) == 2
                put_release.set()
                assert pending_upload.result(timeout=5).status_code == 503
                with storage.open(record.upload_key) as stream:
                    assert stream.read() == wav_bytes()
            else:
                pending_gc = pool.submit(gc, client, record.workspace_id)
                assert delete_started.wait(5)
                put_release.set()
                assert pending_upload.result(timeout=5).status_code == 503
                delete_release.set()
                assert pending_gc.result(timeout=5) == 0
            with client.app.state.session_factory() as db:
                row = db.get(ReferenceRequest, record.id)
                assert (
                    row.run_id is None and row.upload_state == "orphan" and row.upload_write_settled
                )
            delete_release.set()
            assert gc(client, record.workspace_id) == 1
            with pytest.raises(FileNotFoundError):
                storage.open(record.upload_key)
        finally:
            put_release.set()
            delete_release.set()


def test_request_alias_foreign_keys_cannot_point_to_another_project_or_workspace(execution_project):
    from sqlalchemy.exc import IntegrityError

    from videotranslate.execution.service import create_run
    from videotranslate.models.core import Workspace, new_id
    from videotranslate.models.execution import RunRequestKey

    client, _, p = execution_project
    sf = client.app.state.session_factory
    with sf.begin() as db:
        project = db.get(Project, p["id"])
        run = create_run(db, project.workspace_id, project.id, RunCreate(stage="probe"), "owned-A")
        other_workspace = Workspace(id=new_id(), name="Other")
        db.add(other_workspace)
        db.flush()
        neighbor = Project(id=new_id(), workspace_id=project.workspace_id, name="Neighbor")
        foreign = Project(id=new_id(), workspace_id=other_workspace.id, name="Foreign")
        db.add_all([neighbor, foreign])
    for wrong in (neighbor, foreign):
        with pytest.raises(IntegrityError), sf.begin() as db:
            db.add(
                RunRequestKey(
                    project_id=wrong.id,
                    workspace_id=wrong.workspace_id,
                    run_id=run.id,
                    key="owned-A",
                    request_fingerprint=run.request_fingerprint,
                )
            )
            db.flush()


def test_transient_reference_failure_keeps_recoverable_raw_input(dubbing_project, monkeypatch):
    client, headers, p = dubbing_project
    response = upload(dubbing_project)
    storage = client.app.state.storage
    original = type(storage).open

    def unavailable(self, key, *args, **kw):
        if "/reference-uploads/" in key:
            raise OSError("test-only transient storage read")
        return original(self, key, *args, **kw)

    monkeypatch.setattr(type(storage), "open", unavailable)
    assert Worker(client.app.state.settings).run_once()
    with client.app.state.session_factory() as db:
        record = db.scalar(select(ReferenceRequest).where(ReferenceRequest.project_id == p["id"]))
        run = db.get(StageRun, record.run_id)
        assert run.status == "failed" and run.safe_error["code"] == "INTERNAL_ERROR"
    assert gc(client, record.workspace_id) == 0
    monkeypatch.setattr(type(storage), "open", original)
    assert (
        client.post(
            "/api/runs/" + response.json()["run"]["id"] + "/retry", headers=headers, json={}
        ).status_code
        == 200
    )
    assert Worker(client.app.state.settings).run_once()
    assert client.get(f"/api/projects/{p['id']}/references").json()["total"] == 1


def test_cancelled_raw_reference_is_collectible_but_foreign_storage_key_is_not(dubbing_project):
    from videotranslate.models.core import Asset

    client, headers, p = dubbing_project
    response = upload(dubbing_project)
    assert (
        client.post(
            "/api/runs/" + response.json()["run"]["id"] + "/cancel", headers=headers
        ).status_code
        == 200
    )
    with client.app.state.session_factory.begin() as db:
        record = db.scalar(select(ReferenceRequest).where(ReferenceRequest.project_id == p["id"]))
        original_key = record.upload_key
        source = db.get(Asset, p["source_asset_id"])
        record.upload_key = source.storage_key
    assert gc(client, record.workspace_id) == 0
    with client.app.state.storage.open(source.storage_key) as stream:
        assert stream.read(8)
    with client.app.state.session_factory.begin() as db:
        db.get(ReferenceRequest, record.id).upload_key = original_key
    assert gc(client, record.workspace_id) == 1


def test_unknown_submission_is_shared_across_request_keys_without_ack_bypass(
    dubbing_project, monkeypatch
):
    from videotranslate.execution.contracts import FailureCode, StageFailure
    from videotranslate.execution.service import fail_run

    client, headers, _ = dubbing_project
    base, provider = prepare_extract(dubbing_project, monkeypatch)
    first = client.post(
        base + "/runs",
        headers=headers | {"Idempotency-Key": "uncertain-A"},
        json={"stage": "separate"},
    ).json()
    with client.app.state.session_factory.begin() as db:
        run = claim_run(db, "uncertain-worker")
    ctx = RunContext(
        client.app.state.session_factory,
        client.app.state.storage,
        client.app.state.settings,
        run.id,
        run.lease_token,
    )
    operations = Operations(ctx)
    operations.prepare(
        provider="demucs",
        model="htdemucs_ft",
        connection_revision=1,
        host="https://recording.hf.space",
        prefix="/gradio_api",
    )
    operations.begin()
    with ctx.session_factory.begin() as db:
        fail_run(db, run.id, run.lease_token, StageFailure(FailureCode.SUBMISSION_UNCERTAIN))
    second = client.post(
        base + "/runs",
        headers=headers | {"Idempotency-Key": "uncertain-B"},
        json={"stage": "separate"},
    )
    assert second.json()["id"] == first["id"] and second.json()["status"] == "needs_review"
    assert not Worker(client.app.state.settings).run_once() and provider.posts == []
    replay = client.post(
        base + "/runs",
        headers=headers | {"Idempotency-Key": "uncertain-B"},
        json={"stage": "probe"},
    )
    assert replay.status_code == 409 and replay.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"


def test_bounded_raw_cleanup_rotates_protected_reservations(dubbing_project, monkeypatch):
    client, _, p = dubbing_project
    first = failed_partial_upload(dubbing_project, monkeypatch)
    assert upload(dubbing_project).status_code == 503
    with client.app.state.session_factory.begin() as db:
        record = db.get(ReferenceRequest, first.id)
        record.upload_state = "writing"
        record.upload_lease_expires_at = utcnow() + timedelta(hours=1)

    def one():
        return cleanup_orphans(
            client.app.state.session_factory,
            client.app.state.storage,
            workspace_id=first.workspace_id,
            before=utcnow() + timedelta(days=1),
            limit=1,
        )

    assert one() == 0
    assert one() == 1, "a protected older input must not starve later garbage forever"
    with client.app.state.storage.open(first.upload_key) as stream:
        assert stream.read() == wav_bytes()

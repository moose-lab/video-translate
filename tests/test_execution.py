"""Durable execution tests use real database transactions; remote doubles stay in tests."""

import importlib.util

import pytest
from pydantic import ValidationError
from sqlalchemy import inspect


def test_execution_schema_and_strict_contracts(client_factory):
    assert importlib.util.find_spec("videotranslate.models.execution"), "Execution schema missing"
    from videotranslate.execution.contracts import RunCreate, RunRetry
    from videotranslate.models.execution import InputState, ProjectEvent, RunAttempt, StageRun

    client = client_factory()
    tables = inspect(client.app.state.engine).get_table_names()
    assert {
        StageRun.__tablename__,
        RunAttempt.__tablename__,
        InputState.__tablename__,
        ProjectEvent.__tablename__,
    } <= set(tables)
    assert "event_sequence" in {
        c["name"] for c in inspect(client.app.state.engine).get_columns("projects")
    }
    for body in ({"stage": ""}, {"stage": "x" * 41}, {"stage": "probe", "surprise": True}):
        with pytest.raises(ValidationError):
            RunCreate(**body)
    assert RunRetry().acknowledge_uncertain_submission is False
    with pytest.raises(ValidationError):
        RunRetry(acknowledge_uncertain_submission="yes")


def test_enqueue_idempotency_precise_dependencies_and_events(execution_project):
    client, headers, project = execution_project
    url = f"/api/projects/{project['id']}/runs"
    request_headers = headers | {"Idempotency-Key": "first-probe"}
    first = client.post(url, json={"stage": "probe"}, headers=request_headers)
    assert first.status_code == 201, first.text
    run = first.json()
    assert run["status"] == "queued"
    assert (
        client.post(url, json={"stage": "probe"}, headers=request_headers).json()["id"] == run["id"]
    )
    assert (
        client.post(url, json={"stage": "asr"}, headers=headers).json()["error"]["code"]
        == "STAGE_UNAVAILABLE"
    )
    assert (
        client.post(
            url, json={"stage": "probe", "options": {"secret": "bad"}}, headers=headers
        ).status_code
        == 422
    )
    assert (
        client.post(
            url, json={"stage": "probe", "target_language": "ja"}, headers=headers
        ).status_code
        == 422
    )
    client.patch(
        f"/api/projects/{project['id']}",
        json={"name": "New", "source_track_index": 1},
        headers=headers,
    )
    assert client.get(f"/api/runs/{run['id']}").json()["is_stale"] is False
    events = client.get(f"/api/projects/{project['id']}/events").json()["items"]
    assert [e["sequence"] for e in events] == list(range(1, len(events) + 1))
    assert [e["kind"] for e in events].count("run.queued") == 1
    assert "source.upload_completed" in [e["kind"] for e in events]
    assert "source.track_selected" in [e["kind"] for e in events]
    from videotranslate.execution.inputs import set_inputs
    from videotranslate.models.core import Project

    with client.app.state.session_factory.begin() as db:
        p = db.get(Project, project["id"])
        set_inputs(db, p, {"source.video": "replacement"})
    assert client.get(f"/api/runs/{run['id']}").json()["is_stale"] is True
    conflict = client.post(url, json={"stage": "probe"}, headers=request_headers)
    assert conflict.status_code == 409


def test_dependency_invalidation_is_recursive_and_atomic(execution_project):
    from videotranslate.execution.inputs import capture_inputs, is_current, set_inputs
    from videotranslate.models.core import Project
    from videotranslate.models.execution import StageRun

    client, _, project = execution_project
    sf = client.app.state.session_factory
    with sf.begin() as db:
        p = db.get(Project, project["id"])
        set_inputs(
            db, p, {"segment.1": "old", "segment.2": "keep", "translation.ja.1": "published"}
        )
        snapshot = capture_inputs(db, p, ["segment.1"])
        child_snapshot = capture_inputs(db, p, ["translation.ja.1"])
        for stage, deps, output in [
            ("translate", snapshot, "translation.ja.1"),
            ("tts", child_snapshot, "voice.ja.1"),
        ]:
            db.add(
                StageRun(
                    workspace_id=p.workspace_id,
                    project_id=p.id,
                    stage=stage,
                    scope_key=stage,
                    options={},
                    input_project_revision=p.revision,
                    dependency_snapshot=deps,
                    dependency_fingerprint="a" * 64,
                    request_fingerprint="b" * 64,
                    output_key=output,
                    status="succeeded",
                )
            )
    with sf.begin() as db:
        p = db.get(Project, project["id"])
        set_inputs(db, p, {"segment.1": "changed"})
        assert not is_current(db, p, snapshot)
        assert not is_current(db, p, child_snapshot)
        assert capture_inputs(db, p, ["segment.2"])
        assert all(r.is_stale for r in db.query(StageRun).all())
        db.rollback()
    with sf() as db:
        assert is_current(db, db.get(Project, project["id"]), snapshot)


def test_database_rejects_cross_workspace_execution_rows(
    execution_project, client_factory, register
):
    from sqlalchemy.exc import IntegrityError

    from videotranslate.models.execution import InputState

    client, _, project = execution_project
    other = client_factory(database_url=client.app.state.settings.database_url.get_secret_value())
    foreign = register(other, "foreign@example.com")["workspace"]["id"]
    with client.app.state.session_factory() as db:
        db.add(
            InputState(
                workspace_id=foreign, project_id=project["id"], key="bad", fingerprint="a" * 64
            )
        )
        with pytest.raises(IntegrityError):
            db.commit()


def test_successful_retry_reuses_current_inputs_without_changing_idempotency_history(
    execution_project, tiny_mp4
):
    from videotranslate.execution.worker import Worker

    client, headers, project = execution_project
    url = f"/api/projects/{project['id']}/runs"
    keyed = headers | {"Idempotency-Key": "original-request"}
    run = client.post(url, json={"stage": "probe"}, headers=keyed).json()
    assert Worker(client.app.state.settings).run_once()
    assert client.get(f"/api/runs/{run['id']}").json()["status"] == "succeeded"
    upload = client.post(
        f"/api/projects/{project['id']}/source",
        files={"file": ("new.mp4", tiny_mp4 + b"changed", "video/mp4")},
        headers=headers,
    )
    assert upload.status_code == 201
    assert client.post(f"/api/runs/{run['id']}/retry", json={}, headers=headers).status_code == 200
    assert Worker(client.app.state.settings).run_once()
    assert client.get(f"/api/runs/{run['id']}").json()["status"] == "succeeded"
    reused = client.post(url, json={"stage": "probe"}, headers=headers)
    assert reused.status_code == 201 and reused.json()["id"] == run["id"]
    conflict = client.post(url, json={"stage": "probe"}, headers=keyed)
    assert (
        conflict.status_code == 409 and conflict.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"
    )


def test_cache_uses_normalized_options_and_exact_scope(execution_project):
    from videotranslate.execution.contracts import RunCreate, StageResult
    from videotranslate.execution.registry import STAGES, StageDefinition
    from videotranslate.execution.service import claim_run, create_run, finish_run
    from videotranslate.models.core import Project

    client, _, project = execution_project
    sf = client.app.state.session_factory
    base = STAGES["probe"]
    registry = {
        "probe": StageDefinition("probe", lambda options: options, base.resolve_inputs, base.handle)
    }
    with sf.begin() as db:
        p = db.get(Project, project["id"])
        first = create_run(
            db,
            p.workspace_id,
            p.id,
            RunCreate(stage="probe", options={"a": 1, "nested": {"x": 2, "y": 3}}),
            registry=registry,
        ).id
    with sf.begin() as db:
        lease = claim_run(db, "test", registry=registry)
        assert finish_run(db, first, lease.lease_token, StageResult({}), registry=registry)
    with sf.begin() as db:
        p = db.get(Project, project["id"])
        reordered = create_run(
            db,
            p.workspace_id,
            p.id,
            RunCreate(stage="probe", options={"nested": {"y": 3, "x": 2}, "a": 1}),
            registry=registry,
        )
        changed = create_run(
            db,
            p.workspace_id,
            p.id,
            RunCreate(stage="probe", options={"a": 1, "nested": {"x": 2, "y": 4}}),
            registry=registry,
        )
        assert reordered.id == first and changed.id != first

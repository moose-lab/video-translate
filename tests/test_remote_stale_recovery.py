"""Recording provider is a test double, never real inference."""

import pytest
from sqlalchemy import select

from videotranslate.execution.contracts import FailureCode, RunCreate, StageFailure, StageResult
from videotranslate.execution.inputs import set_inputs
from videotranslate.execution.registry import STAGES, StageDefinition
from videotranslate.execution.service import create_run
from videotranslate.execution.worker import Worker
from videotranslate.models.core import Project, utcnow
from videotranslate.models.execution import InputState, StageRun


@pytest.mark.parametrize("cancel_after_edit", [False, True])
def test_retry_wait_remote_handle_survives_input_edit(execution_project, cancel_after_edit):
    client, headers, project = execution_project
    sf = client.app.state.session_factory
    with sf.begin() as db:
        p = db.get(Project, project["id"])
        run_id = create_run(db, p.workspace_id, p.id, RunCreate(stage="probe")).id
    submitted, polled, published = [], [], []

    def handler(context):
        remote_id = context.remote_checkpoint()
        if remote_id is None:
            context.begin_submission("recording-provider", "recording-model")
            submitted.append("job-1")
            context.record_submission("job-1")
            raise StageFailure(FailureCode.TRANSIENT, retryable=True)
        polled.append(remote_id)
        return StageResult({"duration_ms": 1})

    stage = STAGES["probe"]
    registry = {
        "probe": StageDefinition(
            "probe",
            stage.validate_options,
            stage.resolve_inputs,
            handler,
            lambda *args: published.append(True),
        )
    }
    assert Worker(client.app.state.settings, registry=registry).run_once()
    with sf.begin() as db:
        run = db.get(StageRun, run_id)
        assert run.status == "retry_wait" and run.remote_id == "job-1"
        set_inputs(db, db.get(Project, project["id"]), {"source.video": "new"})
        assert run.status == "retry_wait" and run.is_stale
        run.due_at = utcnow()
    if cancel_after_edit:
        response = client.post(f"/api/runs/{run_id}/cancel", headers=headers)
        assert response.status_code == 200 and response.json()["status"] == "cancelling"
    assert Worker(client.app.state.settings, registry=registry).run_once()
    assert submitted == ["job-1"] and polled == ["job-1"] and not published
    with sf() as db:
        run = db.get(StageRun, run_id)
        assert run.status == ("cancelled" if cancel_after_edit else "stale")
        assert run.is_stale and run.remote_state == "completed" and run.remote_id == "job-1"
        assert (
            db.scalar(
                select(InputState).where(
                    InputState.project_id == project["id"], InputState.key == run.output_key
                )
            )
            is None
        )


@pytest.mark.parametrize("stopped_status", ["failed", "needs_review", "stale"])
@pytest.mark.parametrize("action", ["retry", "cancel"])
def test_stopped_remote_job_survives_edit_until_explicit_resolution(
    execution_project, stopped_status, action
):
    client, headers, project = execution_project
    sf = client.app.state.session_factory
    with sf.begin() as db:
        p = db.get(Project, project["id"])
        run_id = create_run(db, p.workspace_id, p.id, RunCreate(stage="probe")).id
    submitted, polled, published = [], [], []
    allow_terminal = False

    def handler(context):
        remote_id = context.remote_checkpoint()
        if remote_id is None:
            context.begin_submission("recording-provider", "recording-model")
            submitted.append("job-1")
            context.record_submission("job-1")
            remote_id = "job-1"
        polled.append(remote_id)
        if not allow_terminal:
            if stopped_status == "needs_review":
                raise StageFailure(FailureCode.CONFIGURATION, review=True)
            raise StageFailure(FailureCode.TRANSIENT, retryable=True)
        return StageResult({"duration_ms": 1})

    stage = STAGES["probe"]
    registry = {
        "probe": StageDefinition(
            "probe",
            stage.validate_options,
            stage.resolve_inputs,
            handler,
            lambda *args: published.append(True),
        )
    }
    worker = Worker(client.app.state.settings, registry=registry)
    count = 3 if stopped_status in {"failed", "stale"} else 1
    for _ in range(count):
        assert worker.run_once()
        with sf.begin() as db:
            run = db.get(StageRun, run_id)
            run.due_at = utcnow()
    with sf.begin() as db:
        run = db.get(StageRun, run_id)
        if stopped_status == "stale":
            # Previously persisted runs may already have been incorrectly marked stale.
            assert run.status == "failed"
            run.status = "stale"
        assert run.status == stopped_status
        original_snapshot = dict(run.dependency_snapshot)
        set_inputs(db, db.get(Project, project["id"]), {"source.video": "changed"})
        assert run.status == stopped_status and run.is_stale
    assert not worker.run_once(), "stopped remote work must require explicit action"
    if action == "retry":
        response = client.post(f"/api/runs/{run_id}/retry", json={}, headers=headers)
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "queued"
    else:
        response = client.post(f"/api/runs/{run_id}/cancel", headers=headers)
        assert response.status_code == 200 and response.json()["status"] == "cancelling"
    allow_terminal = True
    assert worker.run_once()
    assert submitted == ["job-1"] and polled == ["job-1"] * (count + 1)
    assert not published
    with sf() as db:
        run = db.get(StageRun, run_id)
        assert run.dependency_snapshot == original_snapshot
        assert run.is_stale and run.remote_id == "job-1" and run.remote_state == "completed"
        assert run.status == ("stale" if action == "retry" else "cancelled")
        assert run.attempt_count == count + 1
        assert (
            db.scalar(
                select(InputState).where(
                    InputState.project_id == project["id"], InputState.key == run.output_key
                )
            )
            is None
        )


def test_unidentified_uncertain_submission_still_needs_ack_after_edit(execution_project):
    from datetime import timedelta

    from videotranslate.execution.context import RunContext
    from videotranslate.execution.service import claim_run

    client, headers, project = execution_project
    sf = client.app.state.session_factory
    with sf.begin() as db:
        p = db.get(Project, project["id"])
        run_id = create_run(db, p.workspace_id, p.id, RunCreate(stage="probe")).id
        lease = claim_run(db, "first")
    context = RunContext(
        sf, client.app.state.storage, client.app.state.settings, run_id, lease.lease_token
    )
    context.begin_submission("recording-provider", "recording-model")
    with sf.begin() as db:
        db.get(StageRun, run_id).lease_expires_at = utcnow() - timedelta(seconds=1)
    with sf.begin() as db:
        assert claim_run(db, "restart") is None
    with sf.begin() as db:
        set_inputs(db, db.get(Project, project["id"]), {"source.video": "changed"})
    cancel = client.post(f"/api/runs/{run_id}/cancel", headers=headers)
    assert cancel.status_code == 200 and cancel.json()["status"] != "cancelled"
    retry = client.post(f"/api/runs/{run_id}/retry", json={}, headers=headers)
    assert retry.status_code == 409 and retry.json()["error"]["code"] == "SUBMISSION_UNCERTAIN"
    with sf() as db:
        run = db.get(StageRun, run_id)
        assert run.remote_state == "submitting" and run.remote_id is None

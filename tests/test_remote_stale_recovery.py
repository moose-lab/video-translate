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

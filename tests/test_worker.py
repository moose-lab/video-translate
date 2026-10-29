"""Restart and lease tests. Any remote handler in this module is TEST ONLY."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from sqlalchemy import select

from videotranslate.execution.contracts import RunCreate, StageResult
from videotranslate.execution.service import create_run
from videotranslate.models.core import Project, utcnow
from videotranslate.models.execution import RunAttempt, StageRun


def enqueue(client, project, **kwargs):
    with client.app.state.session_factory.begin() as db:
        return create_run(
            db,
            project["workspace_id"]
            if "workspace_id" in project
            else db.get(Project, project["id"]).workspace_id,
            project["id"],
            RunCreate(stage="probe"),
            **kwargs,
        ).id


def test_two_sessions_claim_exactly_once_and_lost_lease_cannot_finish(execution_project):
    from videotranslate.execution.service import claim_run, finish_run, heartbeat

    client, _, project = execution_project
    sf = client.app.state.session_factory
    run_id = enqueue(client, project)

    def claim(owner):
        with sf.begin() as db:
            return claim_run(db, owner, lease_seconds=60)

    with ThreadPoolExecutor(2) as pool:
        claims = list(pool.map(claim, ["one", "two"]))
    (winner,) = [c for c in claims if c]
    assert winner.id == run_id
    with sf.begin() as db:
        assert not heartbeat(db, run_id, "wrong", 60)
        assert not finish_run(db, run_id, "wrong", StageResult({"duration_ms": 12}))
        assert heartbeat(db, run_id, winner.lease_token, 60)
        assert finish_run(db, run_id, winner.lease_token, StageResult({"duration_ms": 12}))
    with sf() as db:
        assert db.get(StageRun, run_id).status == "succeeded"
        assert len(db.scalars(select(RunAttempt)).all()) == 1


def test_stale_worker_does_not_publish_domain_rows(execution_project):
    from videotranslate.execution.inputs import set_inputs
    from videotranslate.execution.registry import STAGES, StageDefinition
    from videotranslate.execution.service import claim_run, finish_run

    client, _, project = execution_project
    sf = client.app.state.session_factory
    run_id = enqueue(client, project)
    published = []
    stage = STAGES["probe"]
    registry = {
        "probe": StageDefinition(
            "probe",
            stage.validate_options,
            stage.resolve_inputs,
            stage.handle,
            lambda *args: published.append(True),
        )
    }
    with sf.begin() as db:
        lease = claim_run(db, "worker", lease_seconds=60)
    with sf.begin() as db:
        set_inputs(db, db.get(Project, project["id"]), {"source.video": "new"})
    with sf.begin() as db:
        assert finish_run(
            db, run_id, lease.lease_token, StageResult({"duration_ms": 3}), registry=registry
        )
    with sf() as db:
        run = db.get(StageRun, run_id)
        assert run.status == "stale" and run.result == {"duration_ms": 3}
    assert published == []


def test_expired_local_lease_requeues_with_monotonic_attempt_history(execution_project):
    from videotranslate.execution.service import claim_run, finish_run

    client, _, project = execution_project
    sf = client.app.state.session_factory
    run_id = enqueue(client, project)
    with sf.begin() as db:
        old = claim_run(db, "old", lease_seconds=60)
        db.get(StageRun, run_id).lease_expires_at = utcnow() - timedelta(seconds=1)
    with sf.begin() as db:
        new = claim_run(db, "new", lease_seconds=60)
        assert new.id == run_id and new.lease_token != old.lease_token
    with sf.begin() as db:
        assert not finish_run(db, run_id, old.lease_token, StageResult({}))
        assert finish_run(db, run_id, new.lease_token, StageResult({}))
    with sf() as db:
        attempts = db.scalars(select(RunAttempt).order_by(RunAttempt.number)).all()
        assert [(a.number, a.outcome) for a in attempts] == [(1, "lease_expired"), (2, "succeeded")]


def test_transient_retry_budget_and_manual_retry_keep_attempts(execution_project):
    from videotranslate.execution.contracts import FailureCode, StageFailure
    from videotranslate.execution.service import claim_run, fail_run, retry_run

    client, _, project = execution_project
    sf = client.app.state.session_factory
    run_id = enqueue(client, project)
    for number in range(1, 4):
        with sf.begin() as db:
            lease = claim_run(db, "worker")
            assert lease.attempt_count == number
            assert fail_run(
                db, run_id, lease.lease_token, StageFailure(FailureCode.TRANSIENT, retryable=True)
            )
        with sf.begin() as db:
            run = db.get(StageRun, run_id)
            assert run.status == ("retry_wait" if number < 3 else "failed")
            run.due_at = utcnow()
    with sf.begin() as db:
        run = db.get(StageRun, run_id)
        retry_run(db, run.workspace_id, run.id)
    with sf.begin() as db:
        lease = claim_run(db, "worker")
        assert lease.attempt_count == 4 and lease.auto_failures == 0
    with sf() as db:
        assert len(db.scalars(select(RunAttempt)).all()) == 4


def test_remote_submission_checkpoint_survives_restart_and_never_resubmits(execution_project):
    from videotranslate.execution.context import RunContext
    from videotranslate.execution.service import claim_run

    client, _, project = execution_project
    sf = client.app.state.session_factory
    run_id = enqueue(client, project)
    calls = []
    with sf.begin() as db:
        lease = claim_run(db, "first")
    context = RunContext(
        sf, client.app.state.storage, client.app.state.settings, lease.id, lease.lease_token
    )
    assert context.remote_checkpoint() is None
    key = context.begin_submission("test-provider", "test-model")
    calls.append(key)  # TEST ONLY: recording an external POST would occur here.
    context.record_submission("test-job-123")
    with sf.begin() as db:
        db.get(StageRun, run_id).lease_expires_at = utcnow() - timedelta(seconds=1)
    with sf.begin() as db:
        resumed = claim_run(db, "restarted")
    next_context = RunContext(
        sf, client.app.state.storage, client.app.state.settings, resumed.id, resumed.lease_token
    )
    assert next_context.remote_checkpoint() == "test-job-123"
    import pytest

    with pytest.raises(__import__("videotranslate.execution.contracts", fromlist=["StageFailure"]).StageFailure):
        next_context.begin_submission("test-provider", "test-model")
    assert len(calls) == 1


def test_uncertain_submission_needs_explicit_acknowledgment(execution_project):
    import pytest

    from videotranslate.errors import APIError
    from videotranslate.execution.context import RunContext
    from videotranslate.execution.service import claim_run, retry_run

    client, _, project = execution_project
    sf = client.app.state.session_factory
    run_id = enqueue(client, project)
    with sf.begin() as db:
        lease = claim_run(db, "worker")
    context = RunContext(
        sf, client.app.state.storage, client.app.state.settings, run_id, lease.lease_token
    )
    context.begin_submission("test-provider", "test-model")
    with sf.begin() as db:
        db.get(StageRun, run_id).lease_expires_at = utcnow() - timedelta(seconds=1)
    with sf.begin() as db:
        assert claim_run(db, "restarted") is None
    with sf.begin() as db:
        run = db.get(StageRun, run_id)
        assert run.status == "needs_review" and run.safe_error["code"] == "SUBMISSION_UNCERTAIN"
        with pytest.raises(APIError) as error:
            retry_run(db, run.workspace_id, run.id)
        assert error.value.code == "SUBMISSION_UNCERTAIN"
    with sf.begin() as db:
        run = db.get(StageRun, run_id)
        retry_run(db, run.workspace_id, run.id, acknowledge_uncertain_submission=True)
        assert run.remote_state == "not_submitted" and run.request_key is None


def test_cancel_running_requires_worker_and_discards_remote_terminal_result(execution_project):
    from videotranslate.execution.context import RunContext
    from videotranslate.execution.service import cancel_run, claim_run, finish_run

    client, _, project = execution_project
    sf = client.app.state.session_factory
    run_id = enqueue(client, project)
    with sf.begin() as db:
        lease = claim_run(db, "worker")
    context = RunContext(
        sf, client.app.state.storage, client.app.state.settings, run_id, lease.lease_token
    )
    context.begin_submission("test-provider", "test-model")
    context.record_submission("job-1")
    with sf.begin() as db:
        run = db.get(StageRun, run_id)
        cancel_run(db, run.workspace_id, run_id)
        assert run.status == "cancelling"
    assert context.remote_checkpoint() == "job-1"  # Existing work may still be polled.
    with sf.begin() as db:
        assert finish_run(db, run_id, lease.lease_token, StageResult({"duration_ms": 1}))
    with sf() as db:
        run = db.get(StageRun, run_id)
        assert run.status == "cancelled" and run.result is None

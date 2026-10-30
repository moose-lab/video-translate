"""Fenced actual provider receipts, including responses arriving after lease expiry."""

from dataclasses import dataclass

from ..models.analysis import PrivateOperation
from .contracts import FailureCode, LeaseLost, StageFailure
from .events import append_event
from .service import _lock_run_project


@dataclass(frozen=True)
class SubmissionBinding:
    """Captured from the persisted operation before the named POST, never a public input."""

    operation_id: str
    run_id: str
    project_id: str
    workspace_id: str
    generation: str
    input_fingerprint: str
    provider: str
    model: str

    @classmethod
    def capture(cls, operation):
        return cls(
            **{
                field: getattr(operation, field if field != "operation_id" else "id")
                for field in cls.__dataclass_fields__
            }
        )


def record_receipt(context, remote_id, binding):
    """Retain the original operation's truth without transferring leases or publication rights."""
    if not isinstance(binding, SubmissionBinding) or binding.run_id != context.run_id:
        raise LeaseLost()
    with context.session_factory.begin() as db:
        project, run = _lock_run_project(db, context.run_id)
        operation = db.get(PrivateOperation, binding.operation_id)
        expected = {
            "run_id": binding.run_id,
            "project_id": binding.project_id,
            "workspace_id": binding.workspace_id,
            "generation": binding.generation,
            "input_fingerprint": binding.input_fingerprint,
            "provider": binding.provider,
            "model": binding.model,
        }
        if (
            project is None
            or run is None
            or operation is None
            or project.id != binding.project_id
            or project.workspace_id != binding.workspace_id
            or run.project_id != binding.project_id
            or run.workspace_id != binding.workspace_id
            or any(getattr(operation, field) != value for field, value in expected.items())
        ):
            raise LeaseLost()
        if operation.remote_id is not None:
            if operation.remote_id != remote_id:
                raise StageFailure(FailureCode.SUBMISSION_UNCERTAIN, review=True)
            return  # Idempotent actual receipt, including a terminal or prepared operation.
        if operation.phase != "submitting":
            raise LeaseLost()
        current = (
            run.request_key == binding.generation
            and run.dependency_fingerprint == binding.input_fingerprint
            and run.provider == binding.provider
            and run.model == binding.model
        )
        if current and (run.remote_state != "submitting" or run.remote_id is not None):
            raise StageFailure(FailureCode.SUBMISSION_UNCERTAIN, review=True)
        operation.remote_id, operation.phase = remote_id, "accepted"
        if current:
            run.remote_id, run.remote_state = remote_id, "submitted"
        append_event(
            db,
            project,
            "run.submission_receipt",
            run=run,
            facts={
                "remote_id": remote_id,
                "recovery": "current_generation" if current else "historical_generation",
            },
        )

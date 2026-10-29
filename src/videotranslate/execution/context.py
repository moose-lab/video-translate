"""Handlers use independent short transactions for lease and remote checkpoints."""

import secrets
from dataclasses import dataclass

from ..models.core import Asset, utcnow
from .contracts import CancellationRequested, FailureCode, LeaseLost, StageFailure, safe_identifier
from .events import append_event
from .inputs import is_current
from .service import _lock_run_project, _valid_lease, confirm_cancel


@dataclass(frozen=True)
class RunContext:
    session_factory: object
    storage: object
    settings: object
    run_id: str
    lease_token: str
    stop_event: object = None

    def _locked(self, db):
        project, run = _lock_run_project(db, self.run_id)
        if not _valid_lease(run, self.lease_token, utcnow()):
            raise LeaseLost()
        return project, run

    def check_active(self):
        with self.session_factory.begin() as db:
            project, run = self._locked(db)
            if (
                project.deleted_at is not None
                or run.cancel_requested_at
                or run.is_stale
                or not is_current(db, project, run.dependency_snapshot)
                or (self.stop_event and self.stop_event.is_set())
            ):
                raise CancellationRequested()

    def source_asset(self):
        self.check_active()
        with self.session_factory.begin() as db:
            project, _ = self._locked(db)
            asset = db.get(Asset, project.source_asset_id) if project.source_asset_id else None
            if (
                asset is None
                or asset.project_id != project.id
                or asset.workspace_id != project.workspace_id
            ):
                raise StageFailure(FailureCode.INVALID_MEDIA)
            return asset

    def remote_checkpoint(self) -> str | None:
        with self.session_factory.begin() as db:
            _, run = self._locked(db)
            if run.remote_state == "submitting" and run.remote_id is None:
                raise StageFailure(FailureCode.SUBMISSION_UNCERTAIN, review=True)
            return run.remote_id

    def begin_submission(self, provider: str, model: str) -> str:
        provider, model = safe_identifier(provider, 60), safe_identifier(model, 120)
        with self.session_factory.begin() as db:
            project, run = self._locked(db)
            if (
                project.deleted_at is not None
                or run.cancel_requested_at
                or run.is_stale
                or not is_current(db, project, run.dependency_snapshot)
                or (self.stop_event and self.stop_event.is_set())
            ):
                raise CancellationRequested()
            if run.remote_state != "not_submitted" or run.remote_id:
                raise StageFailure(FailureCode.SUBMISSION_UNCERTAIN, review=True)
            run.provider, run.model = provider, model
            run.request_key = run.request_key or secrets.token_hex(32)
            run.remote_state = "submitting"
            append_event(
                db, project, "run.submitting", run=run, facts={"provider": provider, "model": model}
            )
            return run.request_key

    def record_submission(self, remote_id: str):
        remote_id = safe_identifier(remote_id)
        with self.session_factory.begin() as db:
            project, run = self._locked(db)
            if run.remote_state != "submitting" or run.remote_id:
                raise StageFailure(FailureCode.SUBMISSION_UNCERTAIN, review=True)
            # Persist the paid handle even when cancellation arrived during POST.
            run.remote_id, run.remote_state = remote_id, "submitted"
            append_event(db, project, "run.submitted", run=run, facts={"remote_id": remote_id})

    def confirm_cancel(self, *, remote_confirmed=False):
        with self.session_factory.begin() as db:
            return confirm_cancel(
                db, self.run_id, self.lease_token, remote_confirmed=remote_confirmed
            )

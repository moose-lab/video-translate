"""Short private checkpoints, bound to exact run inputs and request generation."""

import json
import secrets
from urllib.parse import urlsplit

from sqlalchemy import select

from ..models.analysis import PrivateOperation
from ..models.core import new_id
from .contracts import FailureCode, StageFailure, StageResult, safe_identifier


def current_operation(db, run):
    if not run.request_key:
        return None
    return db.scalar(
        select(PrivateOperation).where(
            PrivateOperation.run_id == run.id,
            PrivateOperation.project_id == run.project_id,
            PrivateOperation.workspace_id == run.workspace_id,
            PrivateOperation.generation == run.request_key,
            PrivateOperation.input_fingerprint == run.dependency_fingerprint,
        )
    )


def has_prepared(db, run):
    operation = current_operation(db, run)
    return bool(operation and operation.phase in {"prepared", "terminal"})


def bounded(value, limit=2 * 1024 * 1024):
    if not isinstance(value, dict) or len(json.dumps(value, allow_nan=False).encode()) > limit:
        raise ValueError("Invalid private payload")


class Operations:
    def __init__(self, context):
        self.context = context

    def current(self):
        with self.context.session_factory.begin() as db:
            _, run = self.context._locked(db)
            return current_operation(db, run)

    def prepare(
        self, *, provider, model, connection_revision=0, host="", prefix="", request_payload=None
    ):
        provider, model = safe_identifier(provider, 60), safe_identifier(model, 120)
        parts = urlsplit(host)
        if host and (
            parts.scheme != "https"
            or not parts.hostname
            or parts.username
            or parts.password
            or parts.path not in {"", "/"}
            or parts.query
            or parts.fragment
        ):
            raise ValueError("Invalid operation host")
        if (
            not isinstance(connection_revision, int)
            or connection_revision < 0
            or len(prefix) > 100
            or (prefix and not prefix.startswith("/"))
        ):
            raise ValueError("Invalid operation binding")
        bounded(request_payload or {})
        self.context.check_active()
        with self.context.session_factory.begin() as db:
            project, run = self.context._locked(db)
            existing = current_operation(db, run)
            if existing:
                return existing
            if run.remote_state != "not_submitted":
                raise StageFailure(FailureCode.SUBMISSION_UNCERTAIN, review=True)
            run.request_key = run.request_key or secrets.token_hex(32)
            operation = PrivateOperation(
                id=new_id(),
                project_id=project.id,
                workspace_id=project.workspace_id,
                run_id=run.id,
                generation=run.request_key,
                input_fingerprint=run.dependency_fingerprint,
                provider=provider,
                model=model,
                host=host,
                prefix=prefix,
                connection_revision=connection_revision,
                request_payload=request_payload or {},
            )
            db.add(operation)
            db.flush()
            return operation

    def begin(self):
        operation = self.current()
        if not operation or operation.phase != "ready":
            raise StageFailure(FailureCode.SUBMISSION_UNCERTAIN, review=True)
        # Metadata/schema GETs and upload must finish before this exact boundary.
        self.context.begin_submission(operation.provider, operation.model)
        from .receipts import SubmissionBinding

        return SubmissionBinding.capture(operation)

    def accept(self, remote_id, *, binding=None):
        # Deliberately does not check cancellation: a paid handle must survive it.
        self.context.record_submission(remote_id, binding=binding)

    def terminal(self, files):
        bounded(files)
        with self.context.session_factory.begin() as db:
            _, run = self.context._locked(db)
            operation = current_operation(db, run)
            if not operation or operation.phase not in {"accepted", "terminal"}:
                raise ValueError("No accepted operation")
            operation.terminal_payload, operation.phase = files, "terminal"
            # Terminal SSE has been consumed; retain ID and known files privately.
            run.remote_state = "completed"

    def cache(self, payload, facts):
        bounded(payload)
        bounded(facts, 65536)
        with self.context.session_factory.begin() as db:
            _, run = self.context._locked(db)
            operation = current_operation(db, run)
            if not operation or operation.phase not in {
                "ready",
                "submitting",
                "accepted",
                "terminal",
                "prepared",
            }:
                raise ValueError("No recoverable operation")
            operation.prepared_payload, operation.public_facts = payload, facts
            operation.phase = "prepared"
            run.remote_state = "completed"
            return StageResult(facts, operation.id)

    def cached(self):
        operation = self.current()
        if operation and operation.phase == "prepared":
            return StageResult(operation.public_facts, operation.id)
        return None

    def payload(self, prepared_id):
        operation = self.current()
        if not operation or operation.id != prepared_id or operation.phase != "prepared":
            raise ValueError("Prepared result does not match run inputs")
        return operation.prepared_payload

    def failed(self):
        with self.context.session_factory.begin() as db:
            _, run = self.context._locked(db)
            operation = current_operation(db, run)
            if not operation:
                raise ValueError("No operation")
            operation.phase, run.remote_state = "failed", "completed"


def store_audio(context, operation_id, audio, kind):
    """Reserve orphan lineage BEFORE storage I/O; no long database transaction."""
    from ..models.analysis import PreparedObject

    with context.session_factory.begin() as db:
        project, run = context._locked(db)
        operation = current_operation(db, run)
        if not operation or operation.id != operation_id:
            raise ValueError("Operation mismatch")
        object_id, token = new_id(), secrets.token_hex(32)
        key = f"{project.workspace_id}/{project.id}/prepared/{object_id}"
        record = PreparedObject(
            id=object_id,
            project_id=project.id,
            workspace_id=project.workspace_id,
            operation_id=operation_id,
            storage_key=key,
            metadata_json=audio.metadata() | {"kind": kind},
            reservation_token=token,
        )
        db.add(record)
    try:
        with audio.path.open("rb") as source:
            context.storage.put(key, source, "audio/wav")
    finally:
        from .prepared_objects import settle_prepared

        with context.session_factory.begin() as db:
            active = settle_prepared(db, context, object_id, token)
        if not active:
            from .contracts import LeaseLost

            raise LeaseLost()
    return object_id


def publish_objects(db, run, object_ids):
    from ..models.analysis import PreparedObject
    from ..models.core import Asset

    operation = current_operation(db, run)
    if not operation or operation.phase != "prepared":
        raise ValueError("No prepared media")
    assets = {}
    for object_id in object_ids:
        record = db.get(PreparedObject, object_id)
        if (
            not record
            or record.operation_id != operation.id
            or record.project_id != run.project_id
            or record.workspace_id != run.workspace_id
            or record.state != "orphan"
            or not record.write_settled
            or record.delete_pending
        ):
            raise ValueError("Invalid prepared media lineage")
        data = record.metadata_json
        asset = Asset(
            id=new_id(),
            project_id=run.project_id,
            workspace_id=run.workspace_id,
            filename="audio.wav",
            content_type="audio/wav",
            storage_key=record.storage_key,
            kind=data["kind"],
            sha256=data["sha256"],
            byte_size=data["byte_size"],
        )
        db.add(asset)
        db.flush()
        record.state, record.asset_id = "published", asset.id
        assets[asset.kind] = asset.id
    return assets


def cleanup_orphans(session_factory, storage, *, workspace_id, before, limit=100):
    """Delete only owned unpublished objects without a recoverable current cache.

    Reserve under the project lock, then delete outside SQL. Published/historical
    assets are protected by both lineage state and the actual storage-key lookup.
    A failed delete remains `deleting` and can be retried safely.
    """
    from .prepared_objects import cleanup_prepared
    from .uploads import cleanup_raw_uploads

    if not workspace_id or not 1 <= limit <= 1000:
        raise ValueError("Explicit cleanup scope required")
    count = cleanup_prepared(
        session_factory, storage, workspace_id=workspace_id, before=before, limit=limit
    )
    if count < limit:
        count += cleanup_raw_uploads(
            session_factory, storage, workspace_id=workspace_id, before=before, limit=limit - count
        )
    return count

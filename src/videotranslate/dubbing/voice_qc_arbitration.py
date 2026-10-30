"""Same-identity preparation/submission arbitration using existing project/worker leases.

All functions here are short SQL-only checkpoints. CPU/storage/network work stays
outside their transactions. Cancelled/expired preparation attempts do not retain
ownership; uncertain submissions always do, until existing explicit reconciliation.
"""

from sqlalchemy import select

from ..errors import APIError
from ..execution.contracts import CancellationRequested, FailureCode, StageFailure, StagePending
from ..execution.inputs import fingerprint
from ..execution.prepared import current_operation
from ..execution.service import _valid_lease
from ..models.analysis import PrivateOperation
from ..models.core import utcnow
from ..models.execution import StageRun
from ..models.voice_qc import VoiceQCCommand, VoiceQCLine
from .ownership import owned, scope
from .voice_qc_cache import cached_recognition


class ReuseAvailable(Exception):
    def __init__(self, reuse):
        self.reuse = reuse
        super().__init__("Prepared recognition available")


def reusable_recognition(db, project, line):
    query = (
        scope(VoiceQCLine, project)
        .join(StageRun, VoiceQCLine.run_id == StageRun.id)
        .join(
            PrivateOperation,
            (PrivateOperation.run_id == StageRun.id)
            & (PrivateOperation.generation == StageRun.request_key)
            & (PrivateOperation.input_fingerprint == StageRun.dependency_fingerprint),
        )
        .join(VoiceQCCommand, VoiceQCLine.command_id == VoiceQCCommand.id)
        .where(
            VoiceQCLine.recognition_identity == line.recognition_identity,
            VoiceQCLine.id != line.id,
            StageRun.project_id == project.id,
            StageRun.workspace_id == project.workspace_id,
            PrivateOperation.project_id == project.id,
            PrivateOperation.workspace_id == project.workspace_id,
            PrivateOperation.phase == "prepared",
            VoiceQCCommand.project_id == project.id,
            VoiceQCCommand.workspace_id == project.workspace_id,
        )
        .order_by(VoiceQCCommand.admission_sequence, VoiceQCLine.id)
        .limit(100)
    )
    candidates = db.scalars(query).all()
    for candidate in candidates:
        if fingerprint(candidate.recognition_input) != fingerprint(line.recognition_input):
            continue
        try:
            payload, origin = cached_recognition(db, project, candidate)
            original = db.scalar(
                scope(VoiceQCLine, project).where(VoiceQCLine.run_id == origin.run_id)
            )
            # A boundary guard may unwind/roll back its Session. Retain only
            # immutable private JSON and IDs, never expired ORM instances.
            return payload, original.id, origin.id
        except (APIError, ValueError, KeyError, TypeError, AttributeError):
            continue
    if len(candidates) == 100:
        raise StageFailure(FailureCode.CONFIGURATION, review=True)
    return None


def checkpoint_guard(line, *, submit=False):
    def guard(db, project, run):
        from .voice_qc import line_current

        if project.deleted_at is not None or run.cancel_requested_at or run.is_stale:
            raise CancellationRequested()
        if not line_current(db, project, line):
            raise StageFailure(FailureCode.CONFIGURATION, review=True)
        now = utcnow()
        peers = db.execute(
            select(StageRun, PrivateOperation)
            .join(VoiceQCLine, VoiceQCLine.run_id == StageRun.id)
            .join(
                PrivateOperation,
                (PrivateOperation.run_id == StageRun.id)
                & (PrivateOperation.generation == StageRun.request_key)
                & (PrivateOperation.input_fingerprint == StageRun.dependency_fingerprint),
            )
            .where(
                StageRun.project_id == project.id,
                StageRun.workspace_id == project.workspace_id,
                VoiceQCLine.project_id == project.id,
                VoiceQCLine.workspace_id == project.workspace_id,
                PrivateOperation.project_id == project.id,
                PrivateOperation.workspace_id == project.workspace_id,
                VoiceQCLine.recognition_identity == line.recognition_identity,
                StageRun.id != run.id,
                PrivateOperation.phase.in_(("ready", "submitting")),
                (PrivateOperation.phase == "submitting")
                | (StageRun.remote_state == "submitting")
                | (
                    StageRun.status.in_(("running", "cancelling"))
                    & (StageRun.lease_expires_at > now)
                ),
            )
            .limit(101)
        ).all()
        if len(peers) > 100:
            raise StageFailure(FailureCode.CONFIGURATION, review=True)
        for peer, operation in peers:
            live = bool(peer.lease_token) and _valid_lease(peer, peer.lease_token, now)
            if peer.remote_state == "submitting" or operation.phase == "submitting":
                if live:
                    raise StagePending()
                raise StageFailure(FailureCode.SUBMISSION_UNCERTAIN, review=True)
        if reusable := reusable_recognition(db, project, line):
            raise ReuseAvailable(reusable)
        for peer, operation in peers:
            if (
                peer.lease_token
                and _valid_lease(peer, peer.lease_token, now)
                and peer.remote_state == "not_submitted"
                and operation.request_payload.get("preparation_attempt") == peer.attempt_count
            ):
                raise StagePending()
        if submit:
            operation = current_operation(db, run)
            if (
                not operation
                or operation.request_payload.get("preparation_attempt") != run.attempt_count
            ):
                raise StageFailure(FailureCode.CONFIGURATION, review=True)

    return guard


def ready_payload(operation, inputs, attempt, metadata=None):
    """Validate old ready-real snapshots before extending an unsubmitted checkpoint."""
    from .synthesis_evidence import AudioEvidence
    from .voice_qc import POLICY

    if operation:
        request = operation.request_payload
        if (
            operation.phase != "ready"
            or operation.provider != "hf_router"
            or operation.model != inputs["config"]["model"]
            or operation.connection_revision != inputs["connection_revision"]
            or operation.host != "https://router.huggingface.co"
            or operation.prefix != "/hf-inference"
            or operation.remote_id is not None
            or operation.terminal_payload is not None
            or set(request)
            not in (
                {"input", "policy", "preprocessing"},
                {"input", "policy", "preprocessing", "preparation_attempt"},
            )
            or fingerprint(request.get("input")) != fingerprint(inputs)
            or fingerprint(request.get("policy")) != fingerprint(POLICY)
        ):
            raise StageFailure(FailureCode.CONFIGURATION, review=True)
        if "preparation_attempt" in request and (
            type(request["preparation_attempt"]) is not int or request["preparation_attempt"] < 1
        ):
            raise StageFailure(FailureCode.CONFIGURATION, review=True)
        prior = request["preprocessing"]
        if prior is not None:
            try:
                AudioEvidence.model_validate(prior)
            except ValueError:
                raise StageFailure(FailureCode.CONFIGURATION, review=True) from None
            if metadata is not None and fingerprint(prior) != fingerprint(metadata):
                raise StageFailure(FailureCode.CONFIGURATION, review=True)
            metadata = prior
        elif "preparation_attempt" not in request:
            raise StageFailure(FailureCode.CONFIGURATION, review=True)
    return {
        "input": inputs,
        "policy": POLICY,
        "preprocessing": metadata,
        "preparation_attempt": attempt,
    }


def cache_reuse(operations, line, reuse):
    payload, original_id, origin_id = reuse
    binding = {
        "input": line.recognition_input,
        "reuse_line_id": original_id,
        "origin_operation_id": origin_id,
        "prepared_fingerprint": fingerprint(payload),
    }

    def pin_guard(db, project, run):
        try:
            current_payload, current_origin = cached_recognition(
                db, project, owned(db, VoiceQCLine, project, original_id)
            )
        except (APIError, ValueError, KeyError, TypeError, AttributeError):
            raise StageFailure(FailureCode.CONFIGURATION, review=True) from None
        if (
            current_origin.id != origin_id
            or fingerprint(current_payload) != binding["prepared_fingerprint"]
        ):
            raise StageFailure(FailureCode.CONFIGURATION, review=True)

    operations.prepare(
        provider="hf_router",
        model=line.recognition_input["config"]["model"],
        connection_revision=line.recognition_input["connection_revision"],
        request_payload=binding,
        guard=pin_guard,
        update_ready=True,
    )
    return operations.cache(
        payload,
        {
            "segment_count": len(payload["recognition"]["segments"]),
            "sha256": payload["preprocessing"]["sha256"],
            "reused": True,
        },
    )

"""Durable local-only reuse intent pinned to the exact original paid proof and manifest."""

from ..execution.inputs import fingerprint
from ..execution.prepared import current_operation
from ..models.execution import StageRun
from ..models.synthesis import SynthesisLine
from .ownership import owned
from .synthesis_evidence import AliasBinding, validate_operation


def capture_alias(origin, origin_run, payload, record):
    return AliasBinding(
        line_id=origin_run.options["line_id"],
        operation_id=origin.id,
        generation=origin.generation,
        input_fingerprint=origin.input_fingerprint,
        prepared_sha256=fingerprint(payload),
        provenance_sha256=fingerprint(record.metadata_json["provenance"]),
    ).model_dump()


def validate_alias(operation, origin, origin_run, payload, record):
    captured = AliasBinding.model_validate(operation.request_payload["reuse"]).model_dump()
    if captured != capture_alias(origin, origin_run, payload, record):
        raise ValueError("Local synthesis alias origin changed")


def resume_alias(db, project, line, operation):
    from .synthesis_cache import cached_payload

    validate_operation(operation, line.input_payload, producing=False)
    run = owned(db, StageRun, project, line.run_id)
    if (
        operation.phase != "ready"
        or run.remote_state != "not_submitted"
        or run.provider is not None
        or run.model is not None
        or run.remote_id is not None
    ):
        raise ValueError("Invalid ready local synthesis alias")
    binding = AliasBinding.model_validate(operation.request_payload.get("reuse"))
    source = owned(db, SynthesisLine, project, binding.line_id)
    if (
        source.id == line.id
        or source.track_id != line.track_id
        or source.segment_id != line.segment_id
        or source.input_fingerprint != line.input_fingerprint
    ):
        raise ValueError("Invalid local synthesis alias source")
    payload, origin_run, record = cached_payload(db, project, source)
    origin = current_operation(db, origin_run)
    if origin is None:
        raise ValueError("Missing original synthesis producer")
    validate_alias(operation, origin, origin_run, payload, record)
    return payload

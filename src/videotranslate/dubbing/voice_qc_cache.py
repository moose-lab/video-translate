"""Strict stored recognition/provenance and pinned local reuse; no I/O."""

from ..execution.inputs import fingerprint
from ..execution.prepared import current_operation
from ..models.voice_qc import VoiceQCLine
from .ownership import owned


def cached_recognition(db, project, line):
    """Check private original operation + settled preprocessing manifest before reuse."""
    from ..execution.prepared import bounded
    from ..models.analysis import PreparedObject
    from ..models.execution import StageRun
    from ..providers.hf_router import normalize_asr
    from .remote_voice_qc import line_for
    from .voice_qc import POLICY

    run = owned(db, StageRun, project, line.run_id)
    if line_for(db, project, run).id != line.id:
        raise ValueError("Invalid recognition line")
    operation = current_operation(db, run)
    if operation is None or operation.phase != "prepared":
        raise ValueError("Recognition unavailable")
    request, payload = operation.request_payload, operation.prepared_payload
    bounded(request)
    bounded(payload)
    if (
        fingerprint(request.get("input")) != fingerprint(line.recognition_input)
        or payload.get("identity") != line.recognition_identity
    ):
        raise ValueError("Recognition input mismatch")
    if set(payload) != {
        "identity",
        "source_sha256",
        "preprocessing",
        "objects",
        "recognition",
        "working_timings",
    }:
        raise ValueError("Unexpected recognition payload")
    if (
        operation.remote_id is not None
        or operation.terminal_payload is not None
        or run.remote_id is not None
        or run.remote_state != "completed"
    ):
        raise ValueError("Invalid synchronous recognition receipt")
    if "reuse_line_id" in request:
        if (
            operation.provider != "hf_router"
            or operation.model != line.recognition_input["config"]["model"]
            or operation.connection_revision != line.recognition_input["connection_revision"]
            or operation.host
            or operation.prefix
            or run.provider is not None
            or run.model is not None
        ):
            raise ValueError("Invalid local alias receipt")
        original_payload, original_operation = resume_alias(db, project, line, operation)
        if fingerprint(original_payload) != fingerprint(payload) or fingerprint(
            operation.public_facts
        ) != fingerprint(
            {
                "segment_count": len(payload["recognition"]["segments"]),
                "sha256": payload["preprocessing"]["sha256"],
                "reused": True,
            }
        ):
            raise ValueError("Recognition alias changed")
        return payload, original_operation
    if set(request) != {"input", "policy", "preprocessing"}:
        raise ValueError("Unexpected recognition request")
    expected = line.recognition_input
    if (
        run.provider != operation.provider
        or run.model != operation.model
        or operation.provider != "hf_router"
        or operation.model != expected["config"]["model"]
        or operation.connection_revision != expected["connection_revision"]
        or operation.remote_id is not None
        or operation.host != "https://router.huggingface.co"
        or operation.prefix != "/hf-inference"
        or fingerprint(request.get("policy")) != fingerprint(POLICY)
        or fingerprint(expected["preprocessing"]) != fingerprint(POLICY)
        or run.dependency_snapshot
        != {"voice_qc.input:" + line.recognition_identity: line.recognition_identity}
    ):
        raise ValueError("Invalid recognition provenance")
    if not isinstance(payload["objects"], list) or len(payload["objects"]) != 1:
        raise ValueError("Invalid recognition manifest")
    record = owned(db, PreparedObject, project, payload["objects"][0])
    from .synthesis_evidence import AudioEvidence

    metadata = AudioEvidence.model_validate(payload["preprocessing"]).model_dump()
    if (
        record.operation_id != operation.id
        or record.state not in {"orphan", "published"}
        or not record.write_settled
        or record.delete_pending
        or metadata != request.get("preprocessing")
        or record.metadata_json != metadata | {"kind": "voice_qc_input"}
        or metadata["sample_rate"] != 16000
        or metadata["channels"] != 1
        or metadata["codec"] != "pcm_s16le"
        or metadata["container"] != "wav"
        or not 0 < metadata["byte_size"] <= 16 * 1024 * 1024
        or payload.get("source_sha256") != expected["audio_sha256"]
    ):
        raise ValueError("Invalid preprocessing evidence")
    if record.asset_id is not None:
        from ..models.core import Asset

        asset = owned(db, Asset, project, record.asset_id)
        if (
            asset.sha256 != metadata["sha256"]
            or asset.byte_size != metadata["byte_size"]
            or asset.storage_key != record.storage_key
            or asset.kind != "voice_qc_input"
        ):
            raise ValueError("Invalid published preprocessing")
    recognition = payload["recognition"]
    normalized = normalize_asr(
        {
            "chunks": [
                {"text": r["text"], "timestamp": [r["start"], r["end"]]}
                for r in recognition["segments"]
            ]
        }
    )
    if normalized != recognition["segments"]:
        raise ValueError("Invalid saved recognition")
    timings = validate_recognition(recognition, metadata["duration_ms"], operation.model)
    if payload.get("working_timings") != timings:
        raise ValueError("Invalid working timing evidence")
    if fingerprint(operation.public_facts) != fingerprint(
        {
            "segment_count": len(normalized),
            "sha256": metadata["sha256"],
            "reused": False,
        }
    ):
        raise ValueError("Invalid recognition facts")
    return payload, operation


def validate_recognition(value, duration, model):
    import re

    from .analysis import working_timings
    from .analysis_contracts import NormalizedTranscript

    if set(value) != {"segments", "detected_language"} or (
        value["detected_language"] is not None
        and (
            not isinstance(value["detected_language"], str)
            or not re.fullmatch(r"[A-Za-z][A-Za-z0-9-]{0,39}", value["detected_language"])
        )
    ):
        raise ValueError("Invalid reported language")
    # Reuse actual bounded provider transcript validator, with no fake language/ID.
    NormalizedTranscript.model_validate({"selection_id": "qc", **value})
    return working_timings(value["segments"], duration, "hf_asr", model=model)


def resume_alias(db, project, line, operation):
    request = operation.request_payload
    if set(request) != {
        "input",
        "reuse_line_id",
        "origin_operation_id",
        "prepared_fingerprint",
    } or fingerprint(request["input"]) != fingerprint(line.recognition_input):
        raise ValueError("Invalid pinned recognition alias")
    original = owned(db, VoiceQCLine, project, request["reuse_line_id"])
    from ..models.execution import StageRun

    origin_run = owned(db, StageRun, project, original.run_id)
    direct = current_operation(db, origin_run)
    if direct is None or "reuse_line_id" in direct.request_payload:
        raise ValueError("Alias must pin a producing operation")
    payload, origin = cached_recognition(db, project, original)
    if (
        origin.id != request["origin_operation_id"]
        or fingerprint(payload) != request["prepared_fingerprint"]
        or fingerprint(original.recognition_input) != fingerprint(line.recognition_input)
    ):
        raise ValueError("Pinned recognition changed")
    return payload, origin


def validate_line(db, project, line, output):
    from ..models.dubbing import SourceSelection, TranscriptRevision, TranslationRevision
    from ..models.synthesis import SynthesisLine
    from ..providers.settings import capability_contract, resolve_revision
    from .voice_qc import POLICY

    inputs = line.recognition_input
    if type(inputs.get("connection_revision")) is not int:
        raise ValueError("Invalid configuration revision")
    try:
        config = resolve_revision(
            db, project.workspace_id, "verification", inputs["connection_revision"]
        )
    except LookupError:
        raise ValueError("Missing configuration revision") from None
    caps = capability_contract("verification", "hf_router", model=config.get("model"))
    if fingerprint(inputs) != fingerprint(
        {
            "audio_sha256": output.sha256,
            "config": config,
            "connection_revision": inputs["connection_revision"],
            "preprocessing": POLICY,
            "model_declaration_revision": caps.get("model_declaration_revision"),
        }
    ):
        raise ValueError("Invalid immutable recognition configuration")
    target = owned(db, TranslationRevision, project, line.translation_revision_id)
    generation = owned(db, SynthesisLine, project, output.line_id)
    source = owned(db, SourceSelection, project, line.source_selection_id)
    transcript = owned(db, TranscriptRevision, project, line.transcript_id)
    if (
        transcript.selection_id != source.id
        or target.track_id != line.track_id
        or target.segment_id != line.segment_id
        or line.comparison_input
        != {
            "expected": target.text,
            "target": line.guard_snapshot.get("target_language"),
            "reference": generation.input_payload["reference_text"],
        }
    ):
        raise ValueError("Invalid comparison lineage")
    proof = line.guard_snapshot
    if (
        proof.get("source_selection_id") != source.id
        or proof.get("source_selection_revision") != source.revision
        or proof.get("transcript_id") != transcript.id
        or proof.get("translation_revision_id") != target.id
        or proof.get("target_text_fingerprint") != fingerprint(target.text)
        or proof.get("source_text_fingerprint") != target.source_text_fingerprint
        or proof.get("output_id") != output.id
        or proof.get("audio_sha256") != output.sha256
    ):
        raise ValueError("Invalid captured editor proof")

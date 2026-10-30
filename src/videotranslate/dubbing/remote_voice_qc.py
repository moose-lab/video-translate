"""Synchronous independent ASR with existing durable prepared-object lifecycle."""

from ..errors import APIError
from ..execution.contracts import FailureCode, StageFailure, StageResult
from ..execution.inputs import capture_inputs, fingerprint
from ..execution.prepared import Operations, current_operation
from ..models.voice_qc import VoiceQCCommand, VoiceQCLine
from .analysis import make_http
from .ownership import invalid, owned, scope
from .synthesis_contracts import LineOptions


def line_options(options):
    try:
        return LineOptions.model_validate(options).model_dump()
    except ValueError:
        raise APIError(
            422, "INVALID_OPTIONS", "A guarded recognition command is required"
        ) from None


def line_scope(request):
    return line_options(request.options)["line_id"]


def line_for(db, project, request):
    from ..models.dubbing import LanguageTrack
    from ..models.synthesis import NaturalOutput

    line = owned(db, VoiceQCLine, project, line_options(request.options)["line_id"])
    intent = owned(db, VoiceQCCommand, project, line.command_id)
    track = owned(db, LanguageTrack, project, line.track_id)
    output = owned(db, NaturalOutput, project, line.output_id)
    if (
        request.stage != "voice_qc"
        or request.segment_id != line.segment_id
        or request.target_language != track.tag
        or intent.track_id != track.id
        or output.track_id != track.id
        or output.segment_id != line.segment_id
        or output.sha256 != line.recognition_input.get("audio_sha256")
        or fingerprint(line.recognition_input) != line.recognition_identity
    ):
        invalid()
    return line


def line_inputs(db, project, request):
    line = line_for(db, project, request)
    return capture_inputs(db, project, ["voice_qc.input:" + line.recognition_identity])


def publication_current(db, run):
    from ..models.core import Project

    try:
        return line_for(db, db.get(Project, run.project_id), run).run_id == run.id
    except (APIError, ValueError, KeyError, TypeError):
        return False


def cached_recognition(db, project, line):
    """Check private original operation + settled preprocessing manifest before reuse."""
    from ..execution.prepared import bounded
    from ..models.analysis import PreparedObject
    from ..models.execution import StageRun
    from ..providers.hf_router import normalize_asr
    from .voice_qc import POLICY

    run = owned(db, StageRun, project, line.run_id)
    operation = current_operation(db, run)
    if operation is None or operation.phase != "prepared":
        raise ValueError("Recognition unavailable")
    request, payload = operation.request_payload, operation.prepared_payload
    bounded(request)
    bounded(payload)
    if (
        request.get("input") != line.recognition_input
        or payload.get("identity") != line.recognition_identity
    ):
        raise ValueError("Recognition input mismatch")
    if "reuse_line_id" in request:
        original = owned(db, VoiceQCLine, project, request["reuse_line_id"])
        if original.id == line.id or original.recognition_input != line.recognition_input:
            raise ValueError("Invalid recognition alias")
        # Aliases always point directly to producing operations.
        origin_run = owned(db, StageRun, project, original.run_id)
        origin = current_operation(db, origin_run)
        if origin is None or "reuse_line_id" in origin.request_payload:
            raise ValueError("Invalid recognition origin")
        original_payload, original_operation = cached_recognition(db, project, original)
        if original_payload != payload:
            raise ValueError("Recognition alias changed")
        return payload, original_operation
    expected = line.recognition_input
    if (
        operation.provider != "hf_router"
        or operation.model != expected["config"]["model"]
        or operation.connection_revision != expected["connection_revision"]
        or operation.remote_id is not None
        or operation.host != "https://router.huggingface.co"
        or operation.prefix != "/hf-inference"
        or request.get("policy") != POLICY
        or expected["preprocessing"] != POLICY
        or run.dependency_snapshot
        != {"voice_qc.input:" + line.recognition_identity: line.recognition_identity}
    ):
        raise ValueError("Invalid recognition provenance")
    record = owned(db, PreparedObject, project, payload["prepared_object_id"])
    metadata = payload["preprocessing"]
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
    validate_recognition(recognition, metadata["duration_ms"])
    if operation.public_facts != {
        "segment_count": len(normalized),
        "sha256": metadata["sha256"],
        "reused": False,
    }:
        raise ValueError("Invalid recognition facts")
    return payload, operation


def validate_recognition(value, duration):
    from .analysis import working_timings
    from .analysis_contracts import NormalizedTranscript

    # Reuse actual bounded provider transcript validator, with no fake language/ID.
    NormalizedTranscript.model_validate({"selection_id": "qc", **value})
    working_timings(value["segments"], duration, "hf_asr", model="openai/whisper-large-v3")


def handler(context):
    import tempfile
    from pathlib import Path

    from ..execution.prepared import store_audio
    from ..media.audio import extract_audio, validate_audio
    from ..models.analysis import PreparedObject
    from ..models.core import Asset
    from ..models.synthesis import NaturalOutput
    from ..providers.hf_router import transcribe
    from .analysis import materialize, provider_failure
    from .remote_synthesis import credential_token
    from .synthesis_cache import validate_output_evidence
    from .voice_qc import POLICY, line_current

    operations = Operations(context)
    with context.session_factory.begin() as db:
        project, run = context._locked(db)
        line = line_for(db, project, run)
        if line.run_id != run.id:
            raise StageFailure(FailureCode.CONFIGURATION)
        output = owned(db, NaturalOutput, project, line.output_id)
        try:
            validate_output_evidence(db, project, output)
        except (APIError, ValueError, KeyError, TypeError, AttributeError):
            raise StageFailure(FailureCode.CONFIGURATION, review=True) from None
        existing = current_operation(db, run)
        if existing and existing.phase == "prepared":
            try:
                cached_recognition(db, project, line)
            except (APIError, ValueError, KeyError, TypeError, AttributeError):
                raise StageFailure(FailureCode.CONFIGURATION, review=True) from None
            return StageResult(existing.public_facts, existing.id)
        if existing and existing.phase == "submitting":
            raise StageFailure(FailureCode.SUBMISSION_UNCERTAIN, review=True)
        reusable, original = None, None
        if existing is None:
            for candidate in db.scalars(
                scope(VoiceQCLine, project)
                .where(
                    VoiceQCLine.recognition_identity == line.recognition_identity,
                    VoiceQCLine.id != line.id,
                )
                .order_by(VoiceQCLine.created_at)
                .limit(100)
            ):
                if candidate.recognition_input != line.recognition_input:
                    continue
                try:
                    reusable, origin = cached_recognition(db, project, candidate)
                    original = owned(
                        db,
                        VoiceQCLine,
                        project,
                        db.scalar(
                            scope(VoiceQCLine, project).where(VoiceQCLine.run_id == origin.run_id)
                        ).id,
                    )
                    break
                except (APIError, ValueError, KeyError, TypeError, AttributeError):
                    continue
            if not line_current(db, project, line):
                raise StageFailure(FailureCode.CONFIGURATION, review=True)
        inputs = line.recognition_input
        token = (
            credential_token(db, project, context, inputs["config"]) if reusable is None else None
        )
        asset = owned(db, Asset, project, output.audio_asset_id)
    if reusable is not None:
        operations.prepare(
            provider="hf_router",
            model=inputs["config"]["model"],
            connection_revision=inputs["connection_revision"],
            request_payload={"input": inputs, "reuse_line_id": original.id},
        )
        return operations.cache(
            reusable,
            {
                "segment_count": len(reusable["recognition"]["segments"]),
                "sha256": reusable["preprocessing"]["sha256"],
                "reused": True,
            },
        )
    if not token:
        raise StageFailure(FailureCode.AUTHENTICATION)
    http = None
    try:
        with tempfile.TemporaryDirectory(prefix="vt-voice-qc-") as directory:
            root = Path(directory)
            materialize(context, asset, root / "source", max_bytes=64 * 1024 * 1024)
            raw = validate_audio(
                root / "source",
                max_duration=600,
                check=context.check_active,
                timeout=context.settings.probe_timeout_seconds,
            )
            if raw.sha256 != inputs["audio_sha256"]:
                raise StageFailure(FailureCode.INVALID_MEDIA)
            normalized = extract_audio(
                root / "source",
                root / "asr.wav",
                audio_ordinal=0,
                start_ms=0,
                end_ms=raw.duration_ms,
                sample_rate=16000,
                channels=1,
                audio_only=True,
                check=context.check_active,
                timeout=context.settings.probe_timeout_seconds,
            )
            if normalized.byte_size > 16 * 1024 * 1024:
                raise StageFailure(FailureCode.MEDIA_LIMIT)
            if existing is None:
                existing = operations.prepare(
                    provider="hf_router",
                    model=inputs["config"]["model"],
                    connection_revision=inputs["connection_revision"],
                    host="https://router.huggingface.co",
                    prefix="/hf-inference",
                    request_payload={
                        "input": inputs,
                        "policy": POLICY,
                        "preprocessing": normalized.metadata(),
                    },
                )
            if (
                existing.request_payload
                != {"input": inputs, "policy": POLICY, "preprocessing": normalized.metadata()}
                or existing.phase != "ready"
            ):
                raise StageFailure(FailureCode.CONFIGURATION, review=True)
            with context.session_factory.begin() as db:
                project, run = context._locked(db)
                records = db.scalars(
                    scope(PreparedObject, project).where(
                        PreparedObject.operation_id == existing.id,
                        PreparedObject.write_settled.is_(True),
                        PreparedObject.state == "orphan",
                        PreparedObject.delete_pending.is_(False),
                    )
                ).all()
                object_id = next(
                    (
                        r.id
                        for r in records
                        if r.metadata_json == normalized.metadata() | {"kind": "voice_qc_input"}
                    ),
                    None,
                )
                if not line_current(db, project, line):
                    raise StageFailure(FailureCode.CONFIGURATION, review=True)
            if object_id is None:
                object_id = store_audio(context, existing.id, normalized, "voice_qc_input")
            http = make_http(context)
            operations.begin()
            response = transcribe(
                http,
                audio=normalized.path.read_bytes(),
                model=existing.model,
                token=token,
                include_metadata=True,
            )
            try:
                validate_recognition(response, normalized.duration_ms)
            except ValueError:
                operations.failed()
                raise StageFailure(FailureCode.INVALID_MEDIA) from None
            # No synthetic remote ID. Success survives any later publication conflict.
            return operations.cache(
                {
                    "identity": line.recognition_identity,
                    "source_sha256": inputs["audio_sha256"],
                    "preprocessing": normalized.metadata(),
                    "prepared_object_id": object_id,
                    "recognition": response,
                },
                {
                    "segment_count": len(response["segments"]),
                    "sha256": normalized.sha256,
                    "reused": False,
                },
            )
    except Exception as error:
        failure = provider_failure(operations, error)
        if failure:
            raise failure from None
        raise
    finally:
        if http:
            http.close()


def publish(db, run, result):
    from ..execution.prepared import publish_objects
    from ..models.core import Project, new_id
    from ..models.voice_qc import VoiceQCResult
    from .ownership import owner
    from .qc_comparison import compare
    from .voice_qc import line_current

    project = db.get(Project, run.project_id)
    line = line_for(db, project, run)
    operation = current_operation(db, run)
    if operation is None or operation.id != result.prepared_id:
        raise ValueError("Mismatched recognition publication")
    payload, origin = cached_recognition(db, project, line)
    from ..models.analysis import PreparedObject

    record = owned(db, PreparedObject, project, payload["prepared_object_id"])
    if record.asset_id is None:
        from ..models.execution import StageRun

        publish_objects(db, owned(db, StageRun, project, origin.run_id), [record.id])
    recognized = " ".join(row["text"] for row in payload["recognition"]["segments"])
    comparison = compare(
        line.comparison_input["expected"],
        recognized,
        target=line.comparison_input["target"],
        detected=payload["recognition"]["detected_language"],
        reference=line.comparison_input["reference"],
    )
    saved = VoiceQCResult(
        id=new_id(),
        **owner(project),
        track_id=line.track_id,
        segment_id=line.segment_id,
        line_id=line.id,
        operation_id=origin.id,
        recognition_identity=line.recognition_identity,
        recognition=payload["recognition"],
        comparison=comparison,
    )
    db.add(saved)
    db.flush()
    current = line_current(db, project, line)
    line.publication = {
        "result_id": saved.id,
        "current": current,
        "issue": None if current else "EDITOR_CHANGED",
    }

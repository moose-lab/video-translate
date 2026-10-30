"""Synchronous independent ASR with existing durable prepared-object lifecycle."""

from ..errors import APIError
from ..execution.contracts import FailureCode, StageFailure, StagePending, StageResult
from ..execution.inputs import capture_inputs, fingerprint
from ..execution.prepared import Operations, current_operation
from ..models.voice_qc import VoiceQCCommand, VoiceQCLine
from .analysis import make_http
from .ownership import invalid, owned, scope
from .synthesis_contracts import LineOptions
from .voice_qc_cache import cached_recognition, resume_alias, validate_recognition


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
    from .voice_qc_cache import validate_line

    validate_line(db, project, line, output)
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


def paid_guard(line):
    def guard(db, project, run):
        from .voice_qc import line_current, unresolved_recognition

        if not line_current(db, project, line):
            raise StageFailure(FailureCode.CONFIGURATION, review=True)
        if unresolved_recognition(db, project, line.recognition_identity, exclude_run_id=run.id):
            raise StageFailure(FailureCode.SUBMISSION_UNCERTAIN, review=True)

    return guard


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
    from .voice_qc import POLICY, earlier_active_recognition, line_current, unresolved_recognition

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
        reusable, original, origin = None, None, None
        if existing and "reuse_line_id" in existing.request_payload:
            try:
                reusable, origin = resume_alias(db, project, line, existing)
            except (APIError, ValueError, KeyError, TypeError, AttributeError):
                raise StageFailure(FailureCode.CONFIGURATION, review=True) from None
        if existing and existing.phase == "submitting":
            raise StageFailure(FailureCode.SUBMISSION_UNCERTAIN, review=True)
        if existing is None:
            if unresolved_recognition(
                db, project, line.recognition_identity, exclude_run_id=run.id
            ):
                raise StageFailure(FailureCode.SUBMISSION_UNCERTAIN, review=True)
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
            if reusable is None and earlier_active_recognition(db, project, line):
                raise StagePending()
            if not line_current(db, project, line):
                raise StageFailure(FailureCode.CONFIGURATION, review=True)
        inputs = line.recognition_input
        token = (
            credential_token(db, project, context, inputs["config"]) if reusable is None else None
        )
        asset = owned(db, Asset, project, output.audio_asset_id)
    if reusable is not None:
        if existing is None:
            operations.prepare(
                provider="hf_router",
                model=inputs["config"]["model"],
                connection_revision=inputs["connection_revision"],
                request_payload={
                    "input": inputs,
                    "reuse_line_id": original.id,
                    "origin_operation_id": origin.id,
                    "prepared_fingerprint": fingerprint(reusable),
                },
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
            operations.begin(guard=paid_guard(line))
            response = transcribe(
                http,
                audio=normalized.path.read_bytes(),
                model=existing.model,
                token=token,
                include_metadata=True,
            )
            try:
                timings = validate_recognition(response, normalized.duration_ms, existing.model)
            except ValueError:
                operations.failed()
                raise StageFailure(FailureCode.INVALID_MEDIA) from None
            # No synthetic remote ID. Success survives any later publication conflict.
            return operations.cache(
                {
                    "identity": line.recognition_identity,
                    "source_sha256": inputs["audio_sha256"],
                    "preprocessing": normalized.metadata(),
                    "objects": [object_id],
                    "recognition": response,
                    "working_timings": timings,
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

    record = owned(db, PreparedObject, project, payload["objects"][0])
    if record.asset_id is None:
        from ..models.execution import StageRun

        publish_objects(db, owned(db, StageRun, project, origin.run_id), [record.id])
    recognized = "".join(row["text"] for row in payload["recognition"]["segments"])
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
        recognition=payload["recognition"] | {"working_timings": payload["working_timings"]},
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

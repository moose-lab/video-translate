"""Remote natural synthesis with per-line durable checkpoints."""

from ..errors import APIError
from ..execution.contracts import FailureCode, StageFailure
from ..execution.inputs import capture_inputs, fingerprint
from ..models.synthesis import SynthesisCommand, SynthesisLine
from ..providers.omnivoice import OmniVoiceLanguageUnavailable
from .analysis import make_http
from .ownership import invalid, owned, scope
from .synthesis_cache import cached_payload
from .synthesis_contracts import LineOptions


def line_options(options):
    try:
        return LineOptions.model_validate(options).model_dump()
    except ValueError:
        raise APIError(422, "INVALID_OPTIONS", "A guarded synthesis command is required") from None


def line_scope(request):
    return line_options(request.options)["line_id"]


def line_for(db, project, request):
    line = owned(db, SynthesisLine, project, line_options(request.options)["line_id"])
    intent = owned(db, SynthesisCommand, project, line.command_id)
    if (
        request.stage != "synthesize"
        or request.segment_id != line.segment_id
        or request.target_language != line.input_payload["target"]
        or fingerprint(line.input_payload) != line.input_fingerprint
        or intent.track_id != line.track_id
    ):
        invalid()
    from .synthesis_lineage import validate_lineage

    validate_lineage(db, project, line, intent)
    return line, intent


def line_inputs(db, project, request):
    line, _ = line_for(db, project, request)
    return capture_inputs(db, project, ["synthesis.input:" + line.input_fingerprint])


def publication_current(db, run):
    from ..models.core import Project

    try:
        line, _ = line_for(db, db.get(Project, run.project_id), run)
        return line.run_id == run.id
    except (APIError, ValueError, KeyError):
        return False


def credential_token(db, project, context, config):
    from sqlalchemy import select

    from ..models.providers import WorkspaceCredential
    from ..providers.vault import decrypt_credential

    kind = config.get("credential_ref")
    if kind not in {None, "huggingface"}:
        raise StageFailure(FailureCode.CONFIGURATION)
    if not kind:
        return None
    credential = db.scalar(
        select(WorkspaceCredential).where(
            WorkspaceCredential.workspace_id == project.workspace_id,
            WorkspaceCredential.kind == kind,
        )
    )
    if not credential or not credential.ciphertext:
        raise StageFailure(FailureCode.AUTHENTICATION)
    try:
        return decrypt_credential(context.settings, project.workspace_id, credential.ciphertext)
    except ValueError:
        raise StageFailure(FailureCode.AUTHENTICATION) from None


def validate_preparation(http, operation, inputs, token):
    from ..providers.gradio import GradioClient
    from .synthesis_evidence import validate_operation

    prepared = validate_operation(operation, inputs, producing=True)
    return GradioClient(http, operation.host, operation.prefix, hf_token=token), prepared


def handler(context):
    import tempfile
    from pathlib import Path

    from ..execution.contracts import StagePending
    from ..execution.prepared import Operations, current_operation, store_audio
    from ..media.audio import extract_audio, validate_audio
    from ..models.core import Asset
    from ..providers.omnivoice import normalize_result, prepare_clone
    from .analysis import materialize, provider_failure
    from .synthesis import editor_current

    operations = Operations(context)
    with context.session_factory.begin() as db:
        project, run = context._locked(db)
        line, intent = line_for(db, project, run)
        if line.run_id != run.id:
            raise StageFailure(FailureCode.CONFIGURATION)
        inputs = line.input_payload
        existing = current_operation(db, run)
        if existing and existing.phase == "prepared":
            try:
                cached_payload(db, project, line)
            except (APIError, ValueError, KeyError, TypeError, AttributeError):
                raise StageFailure(FailureCode.CONFIGURATION) from None
            from ..execution.contracts import StageResult

            return StageResult(existing.public_facts, existing.id)
        reusable, reuse_binding = None, None
        if existing is not None and not isinstance(existing.request_payload, dict):
            raise StageFailure(FailureCode.CONFIGURATION, review=True)
        if existing is not None and (
            "reuse" in existing.request_payload or "prepared" not in existing.request_payload
        ):
            from .synthesis_aliases import resume_alias

            try:
                reusable = resume_alias(db, project, line, existing)
            except (APIError, ValueError, KeyError, TypeError, AttributeError):
                raise StageFailure(FailureCode.CONFIGURATION, review=True) from None
        if existing is None and not intent.regenerate:
            for candidate in db.scalars(
                scope(SynthesisLine, project).where(
                    SynthesisLine.input_fingerprint == line.input_fingerprint,
                    SynthesisLine.id != line.id,
                    SynthesisLine.track_id == line.track_id,
                    SynthesisLine.segment_id == line.segment_id,
                )
            ):
                if candidate.input_payload != inputs:
                    continue
                try:
                    reusable, origin_run, record = cached_payload(db, project, candidate)
                    from .synthesis_aliases import capture_alias

                    reuse_binding = capture_alias(
                        current_operation(db, origin_run), origin_run, reusable, record
                    )
                    break
                except (APIError, ValueError, KeyError, TypeError, AttributeError):
                    continue
        if existing is None and not editor_current(db, project, line):
            raise StageFailure(FailureCode.CONFIGURATION, review=True)
        token = (
            credential_token(db, project, context, inputs["config"]) if reusable is None else None
        )
        reference = (
            owned(db, Asset, project, inputs["reference_asset_id"]) if reusable is None else None
        )
    if reusable is not None:
        if existing is None:
            operations.prepare(
                provider="omnivoice",
                model="OmniVoice",
                connection_revision=inputs["connection_revision"],
                request_payload={"input": inputs, "reuse": reuse_binding},
            )
        facts = {
            "duration_ms": reusable["metadata"]["duration_ms"],
            "sha256": reusable["metadata"]["sha256"],
            "reused": True,
        }
        return operations.cache(reusable, facts)
    http = make_http(context)
    try:
        if existing is None:
            with tempfile.TemporaryDirectory(prefix="videotranslate-clone-ref-") as directory:
                source = Path(directory) / "reference.wav"
                materialize(context, reference, source, max_bytes=64 * 1024 * 1024)
                actual = validate_audio(
                    source,
                    max_duration=120,
                    check=context.check_active,
                    timeout=context.settings.probe_timeout_seconds,
                )
                if actual.sha256 != inputs["reference_sha256"] or actual.container != "wav":
                    raise StageFailure(FailureCode.INVALID_MEDIA)
                prepared = prepare_clone(
                    http, inputs=inputs, reference_audio=source.read_bytes(), hf_token=token
                )
            existing = operations.prepare(
                provider="omnivoice",
                model="OmniVoice",
                connection_revision=inputs["connection_revision"],
                host=prepared["host"],
                prefix=prepared["prefix"],
                request_payload={"input": inputs, "prepared": prepared},
            )
        client, prepared = validate_preparation(http, existing, inputs, token)
        if existing.phase == "ready":
            with context.session_factory.begin() as db:
                project, run = context._locked(db)
                line, _ = line_for(db, project, run)
                if not editor_current(db, project, line):
                    raise StageFailure(FailureCode.CONFIGURATION, review=True)
            binding = operations.begin()
            # Exactly one named POST follows the durable ready checkpoint.
            remote_id = client.submit(prepared["api_name"], prepared["args"])
            operations.accept(remote_id, binding=binding)
            existing = operations.current()
        if existing.phase == "submitting":
            raise StageFailure(FailureCode.SUBMISSION_UNCERTAIN, review=True)
        if existing.phase == "accepted":
            result = client.poll(prepared["api_name"], existing.remote_id)
            if result is None:
                raise StagePending()
            terminal = normalize_result(result)
            # Validate opaque FileData before retaining it, with no fetch until checkpointed.
            path = terminal["audio"]["path"]
            if any(ord(c) < 32 for c in path) or len(path) > 10000:
                raise ValueError("Invalid terminal file")
            operations.terminal(terminal)
            existing = operations.current()
        if existing.phase != "terminal":
            raise StageFailure(FailureCode.CONFIGURATION)
        with context.session_factory.begin() as db:
            project, run = context._locked(db)
            cancelled = bool(run.cancel_requested_at or project.deleted_at is not None)
        if cancelled:
            context.confirm_cancel(remote_confirmed=True)
            from ..execution.contracts import CancellationRequested

            raise CancellationRequested()
        downloaded = Path(
            client.download(existing.terminal_payload["audio"], max_bytes=64 * 1024 * 1024)
        )
        try:
            raw = validate_audio(
                downloaded,
                max_duration=600,
                check=context.check_active,
                timeout=context.settings.probe_timeout_seconds,
            )
            with tempfile.TemporaryDirectory(prefix="videotranslate-natural-") as directory:
                if raw.container == "wav" and raw.codec == "pcm_s16le":
                    natural = raw
                else:
                    natural = extract_audio(
                        downloaded,
                        Path(directory) / "natural.wav",
                        audio_ordinal=0,
                        start_ms=0,
                        end_ms=raw.duration_ms,
                        sample_rate=48000,
                        channels=min(raw.channels, 2),
                        audio_only=True,
                        check=context.check_active,
                        timeout=context.settings.probe_timeout_seconds,
                    )
                from .synthesis_evidence import measured_provenance

                object_id = store_audio(
                    context,
                    existing.id,
                    natural,
                    "natural_audio",
                    provenance=measured_provenance(existing, raw.metadata(), natural.metadata()),
                )
        finally:
            downloaded.unlink(missing_ok=True)
        return operations.cache(
            {
                "input_fingerprint": line.input_fingerprint,
                "origin_operation_id": existing.id,
                "objects": [object_id],
                "metadata": natural.metadata(),
                "raw_metadata": raw.metadata(),
                "full_decode": True,
            },
            {"duration_ms": natural.duration_ms, "sha256": natural.sha256, "reused": False},
        )
    except OmniVoiceLanguageUnavailable:
        raise StageFailure(FailureCode.UNSUPPORTED_LANGUAGE) from None
    except (OSError, TimeoutError):
        raise StageFailure(FailureCode.TRANSIENT, retryable=True) from None
    except Exception as error:
        failure = provider_failure(operations, error)
        if failure:
            raise failure from None
        raise
    finally:
        http.close()


def publish(db, run, result):
    from ..execution.prepared import current_operation, publish_objects
    from ..models.core import Project, new_id
    from ..models.dubbing import LanguageTrack, Segment
    from ..models.synthesis import NaturalOutput
    from .ownership import owner
    from .synthesis import editor_current
    from .synthesis_outputs import select_output

    project = db.get(Project, run.project_id)
    line, intent = line_for(db, project, run)
    operation = current_operation(db, run)
    if operation is None or operation.id != result.prepared_id:
        raise ValueError("Mismatched synthesis publication")
    payload, origin_run, record = cached_payload(db, project, line)
    asset_id = record.asset_id
    if asset_id is None:
        asset_id = publish_objects(db, origin_run, payload["objects"])["natural_audio"]
    output = NaturalOutput(
        id=new_id(),
        **owner(project),
        line_id=line.id,
        track_id=line.track_id,
        segment_id=line.segment_id,
        audio_asset_id=asset_id,
        operation_id=operation.id,
        input_fingerprint=line.input_fingerprint,
        **payload["metadata"],
        measurement="ffprobe_full_decode_sha256_v1",
    )
    db.add(output)
    db.flush()
    selected = editor_current(db, project, line)
    if selected:
        select_output(
            db,
            project,
            owned(db, LanguageTrack, project, line.track_id),
            owned(db, Segment, project, line.segment_id),
            output,
            intent.actor_id,
            "replacement" if intent.replace_selected else "generated",
        )
    line.publication = {
        "output_id": output.id,
        "selected": selected,
        "issue": None if selected else "EDITOR_CHANGED",
    }

"""Real CPU extraction and remote-only analysis stages with short publishers."""

import tempfile
from pathlib import Path

from ..errors import APIError
from ..execution.contracts import FailureCode, StageFailure, StagePending
from ..execution.inputs import capture_inputs
from ..execution.prepared import Operations, current_operation, publish_objects, store_audio
from ..models.analysis import AnalysisMedia
from ..models.core import Project
from ..models.dubbing import SourceTrack
from .ownership import owned, owner
from .source import current_selection


def no_options(options):
    if options:
        raise APIError(422, "INVALID_OPTIONS", "Analysis accepts no options")
    return {}


def transcribe_options(options):
    if not options:
        return {}
    from .analysis_contracts import AnalysisReuse

    try:
        return AnalysisReuse.model_validate(options).model_dump()
    except ValueError:
        raise APIError(422, "INVALID_OPTIONS", "Invalid analysis cache reference") from None


def cached_analysis(db, project, source_run_id, snapshot):
    from ..execution.inputs import is_current
    from ..models.execution import StageRun

    source = owned(db, StageRun, project, source_run_id)
    operation = current_operation(db, source)
    if (
        source.stage != "transcribe"
        or source.status != "succeeded"
        or source.is_stale
        or source.dependency_snapshot != snapshot
        or not is_current(db, project, snapshot)
        or operation is None
        or operation.phase != "prepared"
    ):
        raise APIError(409, "INPUT_REQUIRED", "Source analysis cache is unavailable")
    return source, operation


def extract_inputs(db, project, request):
    if request.target_language or request.segment_id:
        raise APIError(422, "INVALID_SCOPE", "Analysis operates on the selected source")
    current_selection(db, project)
    return capture_inputs(
        db, project, ["source.video", "source.selection", "source.audio_track", "source.window"]
    )


def materialize(context, asset, destination, *, max_bytes):
    import hashlib

    digest = hashlib.sha256()
    size = 0
    with context.storage.open(asset.storage_key) as source, destination.open("wb") as output:
        while chunk := source.read(1024 * 1024):
            context.check_active()
            size += len(chunk)
            if size > max_bytes:
                raise StageFailure(FailureCode.MEDIA_LIMIT)
            digest.update(chunk)
            output.write(chunk)
    if size != asset.byte_size or digest.hexdigest() != asset.sha256:
        raise StageFailure(FailureCode.INVALID_MEDIA)


def extract_handler(context):
    from ..media.audio import extract_audio

    operations = Operations(context)
    if cached := operations.cached():
        return cached
    context.check_active()
    with context.session_factory.begin() as db:
        project, _ = context._locked(db)
        selection = current_selection(db, project)
        track = owned(db, SourceTrack, project, selection.track_id)
    asset = context.source_asset()
    if asset.byte_size > context.settings.probe_max_bytes:
        raise StageFailure(FailureCode.MEDIA_LIMIT)
    operation = operations.prepare(provider="cpu", model="ffmpeg")
    with tempfile.TemporaryDirectory(prefix="videotranslate-extract-") as directory:
        root = Path(directory)
        materialize(context, asset, root / "source", max_bytes=context.settings.probe_max_bytes)
        objects = []
        for kind, rate, channels in (("working_audio", 48000, 2), ("asr_audio", 16000, 1)):
            audio = extract_audio(
                root / "source",
                root / f"{kind}.wav",
                audio_ordinal=track.audio_ordinal,
                start_ms=selection.start_ms,
                end_ms=selection.end_ms,
                sample_rate=rate,
                channels=channels,
                check=context.check_active,
                timeout=context.settings.probe_timeout_seconds,
            )
            objects.append(store_audio(context, operation.id, audio, kind))
    return operations.cache(
        {"objects": objects, "selection_id": selection.id},
        {
            "duration_ms": selection.end_ms - selection.start_ms,
            "audio_ordinal": track.audio_ordinal,
            "object_count": len(objects),
        },
    )


def publish_media(db, run, result):
    operation = current_operation(db, run)
    if not operation or operation.id != result.prepared_id:
        raise ValueError("Prepared result mismatch")
    payload = operation.prepared_payload
    assets = publish_objects(db, run, payload["objects"])
    project = db.get(Project, run.project_id)
    db.add(
        AnalysisMedia(
            **owner(project),
            run_id=run.id,
            selection_id=payload["selection_id"],
            **{
                {
                    "working_audio": "working_asset_id",
                    "asr_audio": "asr_asset_id",
                    "vocals": "vocals_asset_id",
                    "instrumental": "instrumental_asset_id",
                }[kind]: asset
                for kind, asset in assets.items()
            },
        )
    )


def make_http(context):
    from ..providers.network import SafeHTTP

    runtime = context.settings
    return SafeHTTP(
        allowed_hosts={
            host.strip().lower()
            for host in runtime.provider_allowed_hosts.split(",")
            if host.strip()
        },
        proxy_url=runtime.provider_proxy_url.get_secret_value() or None,
        use_doh=runtime.provider_dns_over_https,
    )


def media_for(db, project, stage):
    from ..execution.inputs import is_current
    from ..models.execution import StageRun
    from .ownership import scope

    selection = current_selection(db, project)
    rows = db.scalars(
        scope(AnalysisMedia, project)
        .join(StageRun, StageRun.id == AnalysisMedia.run_id)
        .where(
            AnalysisMedia.selection_id == selection.id,
            StageRun.status == "succeeded",
            StageRun.is_stale.is_(False),
        )
        .order_by(AnalysisMedia.created_at.desc(), AnalysisMedia.id)
    ).all()
    for row in rows:
        run = owned(db, StageRun, project, row.run_id)
        if run.stage == stage and is_current(db, project, run.dependency_snapshot):
            return row
    raise APIError(409, "INPUT_REQUIRED", "Prepared media is required")


def separate_inputs(db, project, request):
    extract_inputs(db, project, request)
    media_for(db, project, "extract")
    from .workflow import connection

    if not connection(db, project, "separation"):
        raise APIError(409, "PROVIDER_REQUIRED", "Separation connection required")
    return capture_inputs(
        db, project, ["source.selection", "output.extract", "provider.separation"]
    )


def transcribe_inputs(db, project, request):
    extract_inputs(db, project, request)
    media_for(db, project, "separate")
    from .workflow import connection

    config = connection(db, project, "transcription")
    if not config:
        raise APIError(409, "PROVIDER_REQUIRED", "Transcription connection required")
    validate_source_asr(config.settings, project.source_language, current_selection(db, project))
    snapshot = capture_inputs(
        db,
        project,
        ["source.selection", "output.separate", "source.language", "provider.transcription"],
    )
    if request.options:
        cached_analysis(db, project, request.options["reuse_run_id"], snapshot)
    return snapshot


def validate_source_asr(config, language, selection):
    from ..languages.catalog import resolve
    from ..providers.asr_languages import WHISPER_LANGUAGES

    code = resolve(language)["code"]
    duration = selection.end_ms - selection.start_ms
    adapter = config["adapter"]
    if adapter == "nvidia_stream":
        if code != "en":
            raise APIError(
                422, "UNSUPPORTED_LANGUAGE", "NVIDIA source recognition requires English"
            )
        if duration > 120000:
            raise APIError(
                422, "MEDIA_LIMIT", "NVIDIA source recognition accepts at most 120 seconds"
            )
    elif adapter == "hf_asr":
        known = config.get("model") == "openai/whisper-large-v3"
        if (code == "auto" and not known) or (
            known and code != "auto" and code not in WHISPER_LANGUAGES
        ):
            raise APIError(
                422, "UNSUPPORTED_LANGUAGE", "Source language is not declared by this ASR model"
            )
        if duration * 32 + 4096 > 16 * 1024 * 1024:
            raise APIError(422, "MEDIA_LIMIT", "HF source recognition audio exceeds limit")
    else:
        raise APIError(422, "STAGE_UNAVAILABLE", "Unsupported transcription adapter")


def provider_failure(operations, error):
    from ..providers.contracts import ProviderError, ProviderTerminalError

    if isinstance(error, ProviderTerminalError):
        operations.failed()
        return StageFailure(FailureCode.INVALID_MEDIA)
    if isinstance(error, ProviderError):
        if error.code in {"auth", "quota", "configuration", "invalid_response"}:
            operation = operations.current()
            # Poll/download access failures say nothing about an accepted job's outcome.
            if operation and not operation.remote_id and operation.phase == "submitting":
                operations.failed()
            return StageFailure(
                FailureCode.AUTHENTICATION if error.code == "auth" else FailureCode.CONFIGURATION
            )
        if error.code == "uncertain":
            return StageFailure(FailureCode.SUBMISSION_UNCERTAIN, review=True)
        return StageFailure(FailureCode.TRANSIENT, retryable=True)
    # A received but invalid terminal result must never be polled indefinitely.
    if isinstance(error, ValueError):
        operation = operations.current()
        if operation and not operation.remote_id:
            operations.failed()
        # Malformed/non-UTF8 polling transport is not an authoritative terminal event.
        return StageFailure(FailureCode.INVALID_MEDIA)
    return None


def separate_handler(context):
    from ..media.audio import validate_audio
    from ..models.core import Asset
    from ..providers.demucs import (
        PreparedSeparation,
        normalize_stems,
        prepare_separation,
        submit_prepared,
    )
    from ..providers.gradio import GradioClient
    from .workflow import connection

    operations = Operations(context)
    if cached := operations.cached():
        return cached
    operation = operations.current()
    http = make_http(context)
    downloads = []
    try:
        if operation is None:
            context.check_active()
            with context.session_factory.begin() as db:
                project, _ = context._locked(db)
                media = media_for(db, project, "extract")
                source = owned(db, Asset, project, media.working_asset_id)
                config = connection(db, project, "separation")
                selection = current_selection(db, project)
            with tempfile.TemporaryDirectory(prefix="videotranslate-separate-") as directory:
                audio = Path(directory) / "audio.wav"
                materialize(context, source, audio, max_bytes=64 * 1024 * 1024)
                prepared = prepare_separation(
                    http,
                    audio=audio.read_bytes(),
                    space_id=config.settings["space_id"],
                    model=config.settings["model"],
                )
            operation = operations.prepare(
                provider="demucs",
                model=config.settings["model"],
                connection_revision=config.revision,
                host=prepared.host,
                prefix=prepared.prefix,
                request_payload={
                    "reference": prepared.reference,
                    "selection_id": selection.id,
                    "duration_ms": selection.end_ms - selection.start_ms,
                },
            )
        client = GradioClient(http, operation.host, operation.prefix)
        if operation.phase == "ready":
            prepared = PreparedSeparation(
                operation.host, operation.prefix, operation.request_payload["reference"]
            )
            operations.begin()
            event_id = submit_prepared(http, prepared)
            operations.accept(event_id)
            operation = operations.current()
        if operation.phase == "submitting":
            raise StageFailure(FailureCode.SUBMISSION_UNCERTAIN, review=True)
        files = operation.terminal_payload
        if files is None:
            value = client.poll("predict", operation.remote_id)
            if value is None:
                raise StagePending()
            # Cache terminal FileData BEFORE any download (SSE may be consumable once).
            try:
                files = normalize_stems(value)
            except ValueError:
                operations.failed()
                raise StageFailure(FailureCode.INVALID_MEDIA) from None
            operations.terminal(files)
        objects = []
        for kind in ("vocals", "instrumental"):
            path = client.download(files[kind])
            downloads.append(path)
            try:
                audio = validate_audio(
                    path,
                    expected_duration_ms=operation.request_payload["duration_ms"],
                    timeout=context.settings.probe_timeout_seconds,
                )
            except StageFailure as failure:
                if failure.code in {FailureCode.INVALID_MEDIA, FailureCode.MEDIA_LIMIT}:
                    operations.failed()
                raise
            objects.append(store_audio(context, operation.id, audio, kind))
        return operations.cache(
            {"objects": objects, "selection_id": operation.request_payload["selection_id"]},
            {"duration_ms": operation.request_payload["duration_ms"], "object_count": 2},
        )
    except Exception as error:
        failure = provider_failure(operations, error)
        if failure:
            raise failure from None
        raise
    finally:
        for path in downloads:
            path.unlink(missing_ok=True)
        http.close()


def working_timings(rows, duration_ms, provider):
    """Keep provider originals; bound only NVIDIA's documented 50 ms frame tail."""
    result = []
    for row in rows:
        start, end = round(row["start"] * 1000), round(row["end"] * 1000)
        flags = []
        if row["end"] > duration_ms / 1000:
            if provider != "nvidia_stream" or row["end"] > duration_ms / 1000 + 0.05:
                raise ValueError("Source timing exceeds selected window")
            end = duration_ms
            flags.append("provider_end_clipped")
        if not 0 <= start < end <= duration_ms:
            raise ValueError("Invalid working source timing")
        result.append({"start_ms": start, "end_ms": end, "flags": flags})
    return result


def transcribe_handler(context):
    import wave

    from sqlalchemy import select

    from ..media.audio import extract_audio
    from ..models.core import Asset
    from ..models.providers import WorkspaceCredential
    from ..providers.hf_router import transcribe
    from ..providers.nvidia_stream import stream_remote
    from ..providers.settings import resolve_revision
    from ..providers.vault import decrypt_credential
    from .workflow import connection, publication_current

    with context.session_factory.begin() as db:
        project, run = context._locked(db)
        if run.options.get("reuse_run_id"):
            source, saved = cached_analysis(
                db, project, run.options["reuse_run_id"], run.dependency_snapshot
            )
            from ..execution.contracts import StageResult

            return StageResult(saved.public_facts | {"reused_from_run_id": source.id}, saved.id)

    operations = Operations(context)
    if cached := operations.cached():
        return cached
    operation = operations.current()
    http = None
    try:
        with context.session_factory.begin() as db:
            project, run = context._locked(db)
            if not publication_current(db, run):
                from ..execution.contracts import CancellationRequested

                raise CancellationRequested()
            selection = current_selection(db, project)
            config_row = connection(db, project, "transcription")
            config = (
                resolve_revision(
                    db, project.workspace_id, "transcription", operation.connection_revision
                )
                if operation
                else config_row.settings
            )
            validate_source_asr(config, project.source_language, selection)
            media = media_for(db, project, "separate")
            audio_asset = owned(db, Asset, project, media.vocals_asset_id)
            language = project.source_language
            credential = (
                db.scalar(
                    select(WorkspaceCredential).where(
                        WorkspaceCredential.workspace_id == project.workspace_id,
                        WorkspaceCredential.kind == config.get("credential_ref"),
                    )
                )
                if config.get("credential_ref")
                else None
            )
            token = (
                decrypt_credential(context.settings, project.workspace_id, credential.ciphertext)
                if credential and credential.ciphertext
                else None
            )
        if config["adapter"] == "hf_asr" and not token:
            raise StageFailure(FailureCode.AUTHENTICATION)
        duration = selection.end_ms - selection.start_ms
        with tempfile.TemporaryDirectory(prefix="videotranslate-asr-") as directory:
            root = Path(directory)
            materialize(context, audio_asset, root / "source", max_bytes=64 * 1024 * 1024)
            normalized = extract_audio(
                root / "source",
                root / "asr.wav",
                audio_ordinal=0,
                start_ms=0,
                end_ms=duration,
                sample_rate=16000,
                channels=1,
                audio_only=True,
                check=context.check_active,
                timeout=context.settings.probe_timeout_seconds,
            )
            if operation is None:
                operation = operations.prepare(
                    provider=config["adapter"],
                    model=config["model"],
                    connection_revision=config_row.revision,
                    host="https://router.huggingface.co"
                    if config["adapter"] == "hf_asr"
                    else config["endpoint"],
                    prefix="/hf-inference"
                    if config["adapter"] == "hf_asr"
                    else "/api/diarization/file/stream",
                    request_payload={
                        "selection_id": selection.id,
                        "duration_ms": duration,
                        "language": language,
                        "audio_asset_id": audio_asset.id,
                    },
                )
            if operation.phase == "submitting":
                raise StageFailure(FailureCode.SUBMISSION_UNCERTAIN, review=True)
            if config["adapter"] == "hf_asr":
                audio = normalized.path.read_bytes()
                if len(audio) > 16 * 1024 * 1024:
                    raise StageFailure(FailureCode.MEDIA_LIMIT)
                http = make_http(context)
                operations.begin()
                response = transcribe(
                    http, audio=audio, model=operation.model, token=token, include_metadata=True
                )
                rows, detected_language = response["segments"], response["detected_language"]
            else:
                detected_language = None
                with wave.open(str(normalized.path)) as wav:
                    pcm = wav.readframes(wav.getnframes())
                rows = stream_remote(
                    pcm,
                    source_language=language,
                    max_speakers=config.get("controls", {}).get("max_speakers", 8),
                    endpoint=operation.host,
                    model=operation.model,
                    proxy_url=context.settings.provider_proxy_url.get_secret_value() or None,
                    use_doh=context.settings.provider_dns_over_https,
                    before_send=operations.begin,
                )
        from .analysis_contracts import NormalizedTranscript

        try:
            payload = NormalizedTranscript.model_validate(
                {
                    "segments": rows,
                    "selection_id": selection.id,
                    "detected_language": detected_language,
                }
            )
            working_timings(
                [row.model_dump() for row in payload.segments], duration, operation.provider
            )
        except ValueError:
            operations.failed()
            raise StageFailure(FailureCode.INVALID_MEDIA) from None
        # Synchronous success has no real polling ID. Commit privately before publication.
        return operations.cache(
            payload.model_dump(exclude_none=True),
            {"segment_count": len(rows), "duration_ms": duration},
        )

    except Exception as error:
        failure = provider_failure(operations, error)
        if failure:
            raise failure from None
        raise
    finally:
        if http:
            http.close()


def publish_transcript(db, run, result):
    from ..execution.inputs import set_inputs
    from ..models.dubbing import SourceSelection, Speaker
    from .ownership import changed
    from .segments import insert_segment
    from .source import new_transcript, source_state
    from .speakers import record_revision

    if run.options.get("reuse_run_id"):
        project = db.get(Project, run.project_id)
        _, saved = cached_analysis(
            db, project, run.options["reuse_run_id"], run.dependency_snapshot
        )
        if result.prepared_id != saved.id:
            raise ValueError("Invalid source cache reference")
        from ..execution.events import append_event

        append_event(
            db,
            project,
            "analysis.reused",
            run=run,
            facts={"recovery": "reuse_prepared", "provider": saved.provider, "model": saved.model},
        )
        return  # Review the current manual/source state; never republish old rows.

    operation = current_operation(db, run)
    if not operation or operation.id != result.prepared_id or operation.phase != "prepared":
        raise ValueError("Invalid prepared transcript")
    project = db.get(Project, run.project_id)
    payload = operation.prepared_payload
    state = source_state(db, project)
    selection = owned(db, SourceSelection, project, payload["selection_id"])
    rows = payload["segments"]
    if not rows or len(rows) > 1000:
        raise StageFailure(FailureCode.INVALID_MEDIA)
    from ..providers.contracts import valid_speaker_id

    try:
        timings = working_timings(rows, selection.end_ms - selection.start_ms, operation.provider)
    except ValueError:
        raise StageFailure(FailureCode.INVALID_MEDIA) from None
    for row in rows:
        if (
            not row["text"].strip()
            or len(row["text"]) > 10000
            or (row.get("speaker") is not None and not valid_speaker_id(row["speaker"]))
        ):
            raise StageFailure(FailureCode.INVALID_MEDIA)
    facets = {}
    transcript = new_transcript(
        db, project, state, selection, "worker", "provider", originals=rows, input_facets=facets
    )
    transcript.run_id, transcript.provider = run.id, operation.provider
    transcript.detected_language = payload.get("detected_language")
    labels = {}
    for row, timing in zip(rows, timings, strict=True):
        original_id = row.get("speaker")
        label = str(original_id) if original_id is not None else None
        if original_id is not None and original_id not in labels:
            speaker = Speaker(**owner(project), selection_id=selection.id, name=label)
            db.add(speaker)
            db.flush()
            record_revision(db, project, speaker, "worker")
            labels[original_id] = speaker.id
        insert_segment(
            db,
            project,
            transcript,
            {
                "text": row["text"],
                "start_ms": timing["start_ms"],
                "end_ms": timing["end_ms"],
                "speaker_id": labels.get(original_id),
            },
            "worker",
            provenance="provider",
            label=label,
            analysis_flags=timing["flags"],
            input_facets=facets,
        )
    set_inputs(db, project, facets)
    changed(
        db,
        project,
        "source.recognized",
        transcript_id=transcript.id,
        count=len(rows),
        provider=operation.provider,
        model=operation.model,
    )

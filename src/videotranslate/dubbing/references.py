"""Private reference preparation and explicitly promoted immutable voice bindings."""

import tempfile
from pathlib import Path

from sqlalchemy import func, select

from ..errors import APIError
from ..execution.contracts import RunCreate
from ..execution.inputs import capture_inputs, fingerprint, is_current, set_inputs
from ..execution.prepared import Operations, current_operation, publish_objects, store_audio
from ..models.analysis import (
    ReferenceRequest,
    ReferenceVersion,
    VoiceBinding,
    VoiceBindingVersion,
    VoiceReference,
)
from ..models.core import Asset, Project, new_id
from ..models.dubbing import Segment, SegmentRevision, SourceTrack
from .ownership import changed, check_revision, conflict, owned, owner, scope
from .segments import active_segment
from .source import active_source


def reference_options(options):
    if (
        set(options) != {"request_id"}
        or not isinstance(options["request_id"], str)
        or len(options["request_id"]) != 36
    ):
        raise APIError(422, "INVALID_OPTIONS", "Reference request required")
    return options


def reference_inputs(db, project, request):
    record = owned(db, ReferenceRequest, project, request.options["request_id"])
    if record.origin == "uploaded" and record.upload_state not in {"orphan", "published"}:
        raise APIError(409, "INPUT_REQUIRED", "Reference input must be uploaded again")
    if request.target_language or request.segment_id:
        raise APIError(422, "INVALID_SCOPE", "Reference scope is fixed by its request")
    return record.dependency_snapshot | capture_inputs(
        db, project, ["reference.request." + record.id]
    )


def enqueue(db, project, record):
    from ..execution.service import create_run, run_json

    db.add(record)
    db.flush()
    set_inputs(
        db,
        project,
        {
            "reference.request." + record.id: {
                "payload": fingerprint(record.payload),
                "audio": record.upload_sha256,
            }
        },
    )
    run = create_run(
        db,
        project.workspace_id,
        project.id,
        RunCreate(stage="reference", options={"request_id": record.id}),
        idempotency_key="reference:" + record.id,
    )
    record.run_id = run.id
    db.flush()
    return {"run": run_json(db, run), "reference": None}


def request_extract(db, project, body, actor):
    _, selection, transcript = active_source(db, project, body, require_transcript=True)
    segment = active_segment(db, project, transcript, body.segment_id)
    check_revision(segment, body.segment_revision)
    revision = owned(db, SegmentRevision, project, segment.current_revision_id)
    if revision.text != body.text or revision.speaker_id != body.speaker_id:
        conflict()
    track = owned(db, SourceTrack, project, selection.track_id)
    asset_id = track.source_asset_id
    if body.media == "vocals":
        from .analysis import media_for

        asset_id = media_for(db, project, "separate").vocals_asset_id
    overlap = (
        db.scalar(
            select(Segment.id)
            .join(SegmentRevision, Segment.current_revision_id == SegmentRevision.id)
            .where(
                Segment.project_id == project.id,
                Segment.workspace_id == project.workspace_id,
                Segment.transcript_id == transcript.id,
                Segment.id != segment.id,
                Segment.archived.is_(False),
                SegmentRevision.start_ms < revision.end_ms,
                SegmentRevision.end_ms > revision.start_ms,
            )
            .limit(1)
        )
        is not None
    )
    snapshot = capture_inputs(
        db,
        project,
        [
            "source.selection",
            "source.transcript",
            f"segment.{segment.id}.text",
            f"segment.{segment.id}.timing",
            f"segment.{segment.id}.voice",
        ],
    )
    payload = body.model_dump() | {
        "timing_overlap": overlap,
        "selection_id": selection.id,
        "source_track_id": track.id,
        "source_asset_id": track.source_asset_id,
        "media_asset_id": asset_id,
        "source_revision_id": revision.id,
        "relative_start_ms": revision.start_ms,
        "relative_end_ms": revision.end_ms,
        "absolute_start_ms": selection.start_ms + revision.start_ms,
        "absolute_end_ms": selection.start_ms + revision.end_ms,
        "audio_ordinal": track.audio_ordinal,
    }
    record = ReferenceRequest(
        id=new_id(),
        **owner(project),
        actor_id=actor,
        origin=body.media,
        payload=payload,
        dependency_snapshot=snapshot,
    )
    return enqueue(db, project, record)


def publication_current(db, run):
    project = db.get(Project, run.project_id)
    record = owned(db, ReferenceRequest, project, run.options["request_id"])
    return record.run_id == run.id and is_current(db, project, record.dependency_snapshot)


def reference_handler(context):
    from ..media.audio import extract_audio, validate_audio
    from .analysis import materialize

    operations = Operations(context)
    if cached := operations.cached():
        return cached
    context.check_active()
    with context.session_factory.begin() as db:
        project, run = context._locked(db)
        record = owned(db, ReferenceRequest, project, run.options["request_id"])
        if record.origin != "uploaded":
            asset = owned(db, Asset, project, record.payload["media_asset_id"])
        else:
            asset = None
    operation = operations.prepare(provider="cpu", model="ffmpeg")
    with tempfile.TemporaryDirectory(prefix="videotranslate-reference-") as directory:
        root = Path(directory)
        source, output = root / "source", root / "reference.wav"
        if asset:
            materialize(context, asset, source, max_bytes=context.settings.probe_max_bytes)
            start = (
                record.payload["absolute_start_ms"]
                if record.origin == "source"
                else record.payload["relative_start_ms"]
            )
            end = (
                record.payload["absolute_end_ms"]
                if record.origin == "source"
                else record.payload["relative_end_ms"]
            )
            audio = extract_audio(
                source,
                output,
                audio_ordinal=record.payload["audio_ordinal"] if record.origin == "source" else 0,
                start_ms=start,
                end_ms=end,
                sample_rate=16000,
                channels=1,
                audio_only=record.origin == "vocals",
                timeout=context.settings.probe_timeout_seconds,
                check=context.check_active,
            )
        else:
            size = 0
            with context.storage.open(record.upload_key) as incoming, source.open("wb") as out:
                while chunk := incoming.read(1024 * 1024):
                    context.check_active()
                    size += len(chunk)
                    if size > 64 * 1024 * 1024:
                        from ..execution.contracts import FailureCode, StageFailure

                        raise StageFailure(FailureCode.MEDIA_LIMIT)
                    out.write(chunk)
            if size != record.upload_size:
                from ..execution.contracts import FailureCode, StageFailure

                raise StageFailure(FailureCode.INVALID_MEDIA)
            original = validate_audio(
                source,
                max_duration=120,
                timeout=context.settings.probe_timeout_seconds,
                check=context.check_active,
            )
            audio = extract_audio(
                source,
                output,
                audio_ordinal=0,
                start_ms=0,
                end_ms=original.duration_ms,
                sample_rate=16000,
                channels=1,
                audio_only=True,
                timeout=context.settings.probe_timeout_seconds,
                check=context.check_active,
            )
        import array
        import math
        import wave

        with wave.open(str(output)) as wav:
            samples = array.array("h", wav.readframes(wav.getnframes()))
        flags = ["short"] if audio.duration_ms < 3000 else []
        if record.payload.get("timing_overlap"):
            flags.append("overlap")
        if samples and math.sqrt(sum(x * x for x in samples) / len(samples)) < 50:
            flags.append("silence")
        object_id = store_audio(context, operation.id, audio, "voice_reference")
    return operations.cache(
        {
            "objects": [object_id],
            "request_id": record.id,
            "metadata": audio.metadata(),
            "flags": flags,
        },
        {"duration_ms": audio.duration_ms, "sha256": audio.sha256},
    )


def publish_reference(db, run, result):
    operation = current_operation(db, run)
    if not operation or operation.id != result.prepared_id:
        raise ValueError("Prepared reference mismatch")
    payload = operation.prepared_payload
    project = db.get(Project, run.project_id)
    record = owned(db, ReferenceRequest, project, payload["request_id"])
    assets = publish_objects(db, run, payload["objects"])
    reference = VoiceReference(
        id=new_id(),
        **owner(project),
        origin="uploaded" if record.origin == "uploaded" else "extracted",
    )
    db.add(reference)
    db.flush()
    provenance = {
        key: record.payload[key]
        for key in (
            "source_asset_id",
            "source_track_id",
            "selection_id",
            "source_revision_id",
            "absolute_start_ms",
            "absolute_end_ms",
            "relative_start_ms",
            "relative_end_ms",
            "speaker_id",
        )
        if key in record.payload
    }
    if "segment_id" in record.payload:
        provenance["source_segment_id"] = record.payload["segment_id"]
    version = ReferenceVersion(
        **owner(project),
        reference_id=reference.id,
        audio_asset_id=assets["voice_reference"],
        text=record.payload["text"],
        language=record.payload["language"],
        duration_ms=payload["metadata"]["duration_ms"],
        sha256=payload["metadata"]["sha256"],
        flags=payload["flags"],
        actor_id=record.actor_id,
        run_id=run.id,
        dependency_snapshot=record.dependency_snapshot,
        **provenance,
    )
    db.add(version)
    db.flush()
    if record.origin == "uploaded":
        record.upload_state = "published"
    changed(
        db,
        project,
        "reference.created",
        run=run,
        reference_id=reference.id,
        duration_ms=version.duration_ms,
        fingerprint=version.sha256,
    )


def version_json(db, project, version):
    reference = owned(db, VoiceReference, project, version.reference_id)
    fields = (
        "id",
        "reference_id",
        "parent_version_id",
        "audio_asset_id",
        "text",
        "language",
        "duration_ms",
        "sha256",
        "flags",
        "source_asset_id",
        "source_track_id",
        "selection_id",
        "source_segment_id",
        "source_revision_id",
        "speaker_id",
        "absolute_start_ms",
        "absolute_end_ms",
        "relative_start_ms",
        "relative_end_ms",
        "created_at",
    )
    return {key: getattr(version, key) for key in fields} | {
        "origin": reference.origin,
        "stale": not is_current(db, project, version.dependency_snapshot),
        "quality": "review_required",
    }


def list_versions(db, project, reference_id=None, limit=100, offset=0):
    query = scope(ReferenceVersion, project)
    if reference_id:
        owned(db, VoiceReference, project, reference_id)
        query = query.where(ReferenceVersion.reference_id == reference_id)
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.scalars(
        query.order_by(ReferenceVersion.created_at.desc(), ReferenceVersion.id)
        .limit(limit)
        .offset(offset)
    )
    return {
        "items": [version_json(db, project, row) for row in rows],
        "total": total,
        "available": True,
    }


def new_version(db, project, reference_id, body, actor):
    previous = owned(db, ReferenceVersion, project, body.parent_version_id)
    if previous.reference_id != reference_id:
        conflict()
    values = {
        column.name: getattr(previous, column.name)
        for column in ReferenceVersion.__table__.columns
        if column.name
        not in {"id", "created_at", "parent_version_id", "text", "language", "actor_id"}
    }
    version = ReferenceVersion(
        id=new_id(),
        **values,
        parent_version_id=previous.id,
        text=body.text,
        language=body.language,
        actor_id=actor,
    )
    db.add(version)
    db.flush()
    changed(db, project, "reference.version_created", reference_id=reference_id)
    return version_json(db, project, version)


def binding_for(db, project, key):
    return db.scalar(scope(VoiceBinding, project).where(VoiceBinding.scope_key == key))


def put_binding(db, project, kind, identity_id, body, actor):
    _, selection, transcript = active_source(db, project, body, require_transcript=kind == "line")
    if kind == "line":
        subject = active_segment(db, project, transcript, identity_id)
        check_revision(subject, body.expected_segment_revision)
    else:
        from .speakers import active_speaker

        subject = active_speaker(db, project, identity_id, selection)
        check_revision(subject, body.expected_speaker_revision)
    reference = (
        owned(db, ReferenceVersion, project, body.reference_version_id)
        if body.reference_version_id
        else None
    )
    if reference and not is_current(db, project, reference.dependency_snapshot):
        conflict()
    key = f"{kind}:{identity_id}"
    binding = binding_for(db, project, key)
    if (binding.revision if binding else 0) != body.revision:
        conflict()
    if binding is None:
        binding = VoiceBinding(
            id=new_id(),
            **owner(project),
            scope_key=key,
            segment_id=identity_id if kind == "line" else None,
            speaker_id=identity_id if kind == "role" else None,
        )
        db.add(binding)
        db.flush()
    version = VoiceBindingVersion(
        id=new_id(),
        **owner(project),
        binding_id=binding.id,
        parent_version_id=binding.current_version_id,
        reference_version_id=body.reference_version_id,
        revision=binding.revision + 1,
        actor_id=actor,
    )
    db.add(version)
    db.flush()
    binding.current_version_id, binding.revision = version.id, version.revision
    set_inputs(db, project, {"voice." + key: version.id})
    changed(
        db,
        project,
        "reference.binding_changed",
        revision=binding.revision,
        **{"segment_id" if kind == "line" else "speaker_id": identity_id},
    )
    return {
        "id": binding.id,
        "revision": binding.revision,
        "reference_version_id": version.reference_version_id,
        "version_id": version.id,
        "scope": key,
    }


def effective_voice_inputs(db, project, segment_id):
    """Future synthesis must depend on ONLY the resolved binding plus its audio proof."""
    segment = owned(db, Segment, project, segment_id)
    revision = owned(db, SegmentRevision, project, segment.current_revision_id)
    discriminator = capture_inputs(db, project, ["voice.line:" + segment_id])
    line = binding_for(db, project, "line:" + segment_id)
    candidates = [
        line,
        binding_for(db, project, "role:" + revision.speaker_id) if revision.speaker_id else None,
    ]
    for binding in candidates:
        if not binding or not binding.current_version_id:
            continue
        version = owned(db, VoiceBindingVersion, project, binding.current_version_id)
        if version.reference_version_id:
            reference = owned(db, ReferenceVersion, project, version.reference_version_id)
            return (
                discriminator
                | capture_inputs(db, project, ["voice." + binding.scope_key])
                | reference.dependency_snapshot
            )
    return discriminator


def binding_json(db, project, kind, identity_id, *, history_limit=100, offset=0):
    from ..models.dubbing import Speaker

    owned(db, Speaker if kind == "role" else Segment, project, identity_id)
    binding = binding_for(db, project, f"{kind}:{identity_id}")
    if not binding:
        return {"revision": 0, "reference_version_id": None, "history": [], "total": 0}
    current = owned(db, VoiceBindingVersion, project, binding.current_version_id)
    query = scope(VoiceBindingVersion, project).where(VoiceBindingVersion.binding_id == binding.id)
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.scalars(
        query.order_by(VoiceBindingVersion.revision.desc()).limit(history_limit).offset(offset)
    )
    return {
        "id": binding.id,
        "revision": binding.revision,
        "version_id": current.id,
        "reference_version_id": current.reference_version_id,
        "history": [
            {
                key: getattr(row, key)
                for key in (
                    "id",
                    "parent_version_id",
                    "reference_version_id",
                    "revision",
                    "created_at",
                )
            }
            for row in rows
        ],
        "total": total,
    }

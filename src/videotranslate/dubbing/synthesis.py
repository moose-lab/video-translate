"""Guarded natural clone commands: inference identity is separate from editor permission."""

from sqlalchemy import func, select

from ..errors import APIError
from ..execution.contracts import RunCreate
from ..execution.inputs import fingerprint, initialize_inputs, is_current, set_inputs
from ..models.analysis import ReferenceVersion, VoiceBindingVersion, VoiceReference
from ..models.core import Asset, new_id
from ..models.dubbing import LanguageTrack, SegmentRevision, TranslationRevision
from ..models.execution import StageRun
from ..models.synthesis import AudioSelection, SynthesisCommand, SynthesisLine
from ..providers.omnivoice import clone_arguments
from .ownership import conflict, invalid, owned, owner, scope
from .references import binding_for, effective_voice_inputs
from .segments import active_segment
from .source import active_source, current_selection, source_state
from .synthesis_settings import effective_controls
from .translations import track_for, translation_state

ACTIVE = ("queued", "running", "retry_wait", "cancelling")


def issue(code, message):
    raise APIError(409, code, message)


def validate_config(db, project):
    from .workflow import connection

    config = connection(db, project, "synthesis")
    if not config or config.settings.get("adapter") != "omnivoice":
        issue("PROVIDER_REQUIRED", "An OmniVoice connection is required")
    values = config.settings
    if values.get("model") != "OmniVoice" or not values.get("space_id"):
        issue("PROVIDER_REQUIRED", "Synthesis configuration is unavailable")
    return config


def resolved_reference(db, project, segment):
    revision = owned(db, SegmentRevision, project, segment.current_revision_id)
    for key in (
        "line:" + segment.id,
        "role:" + revision.speaker_id if revision.speaker_id else None,
    ):
        binding = binding_for(db, project, key) if key else None
        if not binding or not binding.current_version_id:
            continue
        version = owned(db, VoiceBindingVersion, project, binding.current_version_id)
        if not version.reference_version_id:
            continue
        reference = owned(db, ReferenceVersion, project, version.reference_version_id)
        owned(db, VoiceReference, project, reference.reference_id)
        asset = owned(db, Asset, project, reference.audio_asset_id)
        if not is_current(db, project, reference.dependency_snapshot):
            issue(
                "REFERENCE_STALE",
                "The effective reference is stale; prepare and review a current version",
            )
        if (
            not reference.text.strip()
            or not 0 < reference.duration_ms <= 120000
            or reference.sha256 != asset.sha256
        ):
            issue("REFERENCE_UNUSABLE", "The effective reference audio or transcript is unusable")
        return version, reference
    issue("REFERENCE_REQUIRED", "An effective line or role reference is required")


def reference_warnings(reference):
    warnings = list(reference.flags)
    if reference.duration_ms < 3000 and "short" not in warnings:
        warnings.append("short")
    if reference.duration_ms > 30000 and "long" not in warnings:
        warnings.append("long")
    return warnings


def inference_inputs(db, project, track, segment):
    state = translation_state(db, project, track, segment)
    if state is None:
        issue("TARGET_REQUIRED", "A current target translation is required")
    target = owned(db, TranslationRevision, project, state.current_revision_id)
    source = owned(db, SegmentRevision, project, segment.current_revision_id)
    if (
        state.stale
        or target.source_text_fingerprint != fingerprint(source.text)
        or not target.text.strip()
    ):
        issue("TARGET_STALE", "The target translation must match the current source wording")
    binding, reference = resolved_reference(db, project, segment)
    config = validate_config(db, project)
    controls, control_versions = effective_controls(
        db, project, track, segment.id, config.settings.get("controls")
    )
    try:
        args = clone_arguments(
            target.text,
            track.tag,
            {"path": "validated-upload-pending"},
            reference.text,
            controls=controls,
        )
    except ValueError:
        raise APIError(
            422, "INVALID_SYNTHESIS_INPUT", "Unsupported synthesis language or controls"
        ) from None
    inputs = {
        "text": target.text,
        "target": track.tag,
        "model_language": args[1],
        "reference_version_id": reference.id,
        "reference_sha256": reference.sha256,
        "reference_text": reference.text,
        "reference_asset_id": reference.audio_asset_id,
        "binding_version_id": binding.id,
        "voice_inputs": effective_voice_inputs(db, project, segment.id),
        "controls": controls,
        "connection_revision": config.revision,
        "config": config.settings,
    }
    return inputs, state, target, reference, control_versions


def selection_for(db, project, track, segment):
    return db.scalar(
        scope(AudioSelection, project).where(
            AudioSelection.track_id == track.id, AudioSelection.segment_id == segment.id
        )
    )


def editor_guard(db, project, track, segment, state, controls):
    selection = current_selection(db, project)
    audio = selection_for(db, project, track, segment)
    revision = owned(db, SegmentRevision, project, segment.current_revision_id)
    return {
        "source_selection_id": selection.id,
        "selection_revision": selection.revision,
        "transcript_id": source_state(db, project).transcript_id,
        "source_text_fingerprint": fingerprint(revision.text),
        "source_revision_id": revision.id,
        "translation_revision": state.revision,
        "translation_revision_id": state.current_revision_id,
        "audio_selection_revision": audio.revision if audio else 0,
        "controls_versions": controls,
    }


def editor_current(db, project, line):
    try:
        track = owned(db, LanguageTrack, project, line.track_id)
        if track.archived:
            return False
        from ..models.dubbing import TranscriptRevision

        transcript_id = source_state(db, project).transcript_id
        transcript = owned(db, TranscriptRevision, project, transcript_id)
        segment = active_segment(db, project, transcript, line.segment_id)
        inputs, state, _, _, controls = inference_inputs(db, project, track, segment)
        # Timing-only source revisions do not change permission for independent uploaded references.
        actual = editor_guard(db, project, track, segment, state, controls)
        old = {k: v for k, v in line.guard_snapshot.items() if k != "source_revision_id"}
        return inputs == line.input_payload and old == {
            k: v for k, v in actual.items() if k != "source_revision_id"
        }
    except (APIError, ValueError, TypeError):
        return False


def command(db, project, tag, body, actor):
    from ..execution.service import create_run

    initialize_inputs(db, project)
    _, selection, transcript = active_source(db, project, body, require_transcript=True)
    track = track_for(db, project, tag)
    if len({r.id for r in body.segments}) != len(body.segments):
        invalid()
    captured, skipped = [], []
    for row in body.segments:
        segment = active_segment(db, project, transcript, row.id)
        inputs, state, target, reference, controls = inference_inputs(db, project, track, segment)
        guard = editor_guard(db, project, track, segment, state, controls)
        if (
            row.translation_revision != state.revision
            or row.expected_source_text_fingerprint != guard["source_text_fingerprint"]
            or row.selection_revision != guard["audio_selection_revision"]
        ):
            conflict()
        if (
            row.review_translation_revision is not None
            and row.review_translation_revision != state.revision
        ):
            conflict()
        if not target.approved and row.review_translation_revision != state.revision:
            issue(
                "TARGET_REVIEW_REQUIRED",
                "Review the exact current target revision before synthesis",
            )
        warnings = reference_warnings(reference)
        if warnings and row.review_reference_version_id != reference.id:
            issue(
                "REFERENCE_REVIEW_REQUIRED",
                "Review the exact effective reference version and its measured warnings",
            )
        if (
            row.review_reference_version_id is not None
            and row.review_reference_version_id != reference.id
        ):
            conflict()
        if guard["audio_selection_revision"] and not body.replace_selected:
            skipped.append(row.id)
        else:
            captured.append((row, inputs, state, reference, guard))
    signature = fingerprint(
        {
            "track": track.id,
            "source_selection": selection.id,
            "transcript": transcript.id,
            "rows": [r.model_dump() for r in body.segments],
            "inputs": [item[1] for item in captured],
            "replace_selected": body.replace_selected,
            "regenerate": body.regenerate,
        }
    )
    previous = db.scalar(
        scope(SynthesisCommand, project).where(SynthesisCommand.signature == signature)
    )
    if previous:
        return command_json(db, project, previous)
    if not captured:
        return {"id": None, "lines": [], "skipped_ids": skipped, "status": "selection_preserved"}
    for row, *_ in captured:
        pending = db.scalar(
            scope(StageRun, project).where(
                StageRun.stage == "synthesize",
                StageRun.target_language == track.tag,
                StageRun.segment_id == row.id,
                ((StageRun.status.in_(ACTIVE)) | (StageRun.remote_state == "submitting")),
            )
        )
        if pending:
            issue(
                "SUBMISSION_UNCERTAIN" if pending.remote_state == "submitting" else "RUN_ACTIVE",
                "Existing line work must be completed or explicitly reconciled",
            )
    intent = SynthesisCommand(
        id=new_id(),
        **owner(project),
        track_id=track.id,
        source_selection_id=selection.id,
        transcript_id=transcript.id,
        selection_revision=selection.revision,
        signature=signature,
        actor_id=actor,
        replace_selected=body.replace_selected,
        regenerate=body.regenerate,
    )
    db.add(intent)
    db.flush()
    for row, inputs, state, reference, guard in captured:
        digest = fingerprint(inputs)
        line = SynthesisLine(
            id=new_id(),
            **owner(project),
            command_id=intent.id,
            track_id=track.id,
            segment_id=row.id,
            translation_revision_id=state.current_revision_id,
            reference_version_id=reference.id,
            binding_version_id=inputs["binding_version_id"],
            input_payload=inputs,
            input_fingerprint=digest,
            guard_snapshot=guard,
            review_translation_revision=row.review_translation_revision,
            review_reference_version_id=row.review_reference_version_id,
        )
        db.add(line)
        db.flush()
        set_inputs(db, project, {"synthesis.input:" + digest: inputs})
        run = create_run(
            db,
            project.workspace_id,
            project.id,
            RunCreate(
                stage="synthesize",
                target_language=track.tag,
                segment_id=row.id,
                options={"line_id": line.id},
            ),
            idempotency_key="synthesis:" + line.id,
            guarded_command=True,
        )
        line.run_id = run.id
    from .ownership import changed

    changed(
        db,
        project,
        "synthesis.queued",
        workflow_id=intent.id,
        count=len(captured),
        target_language=track.tag,
        action="regenerate"
        if body.regenerate
        else "replace"
        if body.replace_selected
        else "generate",
    )
    db.flush()
    return command_json(db, project, intent) | {"skipped_ids": skipped}


def command_json(db, project, intent, limit=100, offset=0):
    query = scope(SynthesisLine, project).where(SynthesisLine.command_id == intent.id)
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    lines = db.scalars(
        query.order_by(SynthesisLine.created_at, SynthesisLine.id).limit(limit).offset(offset)
    ).all()
    statuses = db.scalars(
        select(StageRun.status)
        .join(SynthesisLine, SynthesisLine.run_id == StageRun.id)
        .where(
            SynthesisLine.command_id == intent.id,
            SynthesisLine.project_id == project.id,
            SynthesisLine.workspace_id == project.workspace_id,
        )
    ).all()
    result = []
    for line in lines:
        run = owned(db, StageRun, project, line.run_id)
        result.append(
            {
                "id": line.id,
                "segment_id": line.segment_id,
                "run_id": run.id,
                "status": run.status,
                "publication": line.publication,
                "next_action": "acknowledge_uncertain_submission"
                if run.remote_state == "submitting"
                else "review_natural_audio"
                if line.publication.get("selected")
                else "review_current_selection"
                if line.publication
                else None,
                "review_translation_revision": line.review_translation_revision,
                "review_reference_version_id": line.review_reference_version_id,
            }
        )
    return {
        "id": intent.id,
        "lines": result,
        "regenerate": intent.regenerate,
        "replace_selected": intent.replace_selected,
        "status": "running"
        if any(status in ACTIVE for status in statuses)
        else "incomplete"
        if any(status != "succeeded" for status in statuses)
        else "review",
        "total": total,
        "acceptance": "not_assessed",
    }

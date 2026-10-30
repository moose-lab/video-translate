"""Natural measurements and immutable explicit selections; no listening acceptance."""

from sqlalchemy import func, select

from ..execution.inputs import fingerprint
from ..models.core import new_id
from ..models.dubbing import SegmentRevision, TranscriptRevision
from ..models.synthesis import AudioSelection, AudioSelectionVersion, NaturalOutput, SynthesisLine
from .ownership import changed, conflict, owned, owner, scope
from .segments import active_segment, active_segments_query
from .source import active_source, source_state
from .synthesis import inference_inputs, selection_for
from .translations import track_for, translation_state


def select_output(db, project, track, segment, output, actor, provenance):
    selection = selection_for(db, project, track, segment)
    if selection is None:
        selection = AudioSelection(
            id=new_id(), **owner(project), track_id=track.id, segment_id=segment.id
        )
        db.add(selection)
        db.flush()
    version = AudioSelectionVersion(
        id=new_id(),
        **owner(project),
        selection_id=selection.id,
        track_id=track.id,
        segment_id=segment.id,
        output_id=output.id,
        parent_version_id=selection.current_version_id,
        revision=selection.revision + 1,
        actor_id=actor,
        provenance=provenance,
    )
    db.add(version)
    db.flush()
    selection.revision, selection.current_version_id = version.revision, version.id
    changed(
        db,
        project,
        "synthesis.selection_changed",
        segment_id=segment.id,
        asset_id=output.audio_asset_id,
        revision=selection.revision,
    )


def output_json(db, project, track, segment, output):
    source = owned(db, SegmentRevision, project, segment.current_revision_id)
    slot = source.end_ms - source.start_ms
    stale = True
    try:
        inputs, *_ = inference_inputs(db, project, track, segment)
        stale = fingerprint(inputs) != output.input_fingerprint
    except Exception as error:
        from ..errors import APIError

        if not isinstance(error, (APIError, ValueError)):
            raise
    from ..errors import APIError
    from .synthesis_cache import validate_output_evidence

    evidence_status = "invalid"
    try:
        validate_output_evidence(db, project, output)
        evidence_status = "validated"
    except (APIError, ValueError, TypeError, KeyError, AttributeError):
        pass
    from .voice_qc import output_assessment

    assessment = output_assessment(db, project, track, segment, output)
    assessment["ready"] = assessment["ready"] and not stale and evidence_status == "validated"
    if stale:
        assessment["issues"].append("NATURAL_AUDIO_STALE")
    if evidence_status != "validated":
        assessment["issues"].append("AUDIO_EVIDENCE_INVALID")
    return {
        **assessment,
        "evidence_status": evidence_status,
        "id": output.id,
        "audio_asset_id": output.audio_asset_id,
        "line_id": output.line_id,
        "sha256": output.sha256,
        "natural_duration_ms": output.duration_ms,
        "slot_duration_ms": slot,
        "ratio": output.duration_ms / slot,
        "measurement": output.measurement,
        "sample_rate": output.sample_rate,
        "channels": output.channels,
        "codec": output.codec,
        "container": output.container,
        "stale": stale,
        "created_at": output.created_at,
    }


def history(db, project, tag, segment_id, limit=100, offset=0):
    from ..models.dubbing import Segment

    track = track_for(db, project, tag, active=False)
    segment = owned(db, Segment, project, segment_id)
    selection = selection_for(db, project, track, segment)
    current = (
        owned(db, AudioSelectionVersion, project, selection.current_version_id)
        if selection
        else None
    )
    query = scope(NaturalOutput, project).where(
        NaturalOutput.track_id == track.id, NaturalOutput.segment_id == segment.id
    )
    versions = scope(AudioSelectionVersion, project).where(
        AudioSelectionVersion.track_id == track.id, AudioSelectionVersion.segment_id == segment.id
    )
    return {
        "selection_revision": selection.revision if selection else 0,
        "selected_output_id": current.output_id if current else None,
        "total": db.scalar(select(func.count()).select_from(query.subquery())),
        "outputs": [
            output_json(db, project, track, segment, row)
            for row in db.scalars(
                query.order_by(NaturalOutput.created_at.desc(), NaturalOutput.id)
                .limit(limit)
                .offset(offset)
            )
        ],
        "selection_total": db.scalar(select(func.count()).select_from(versions.subquery())),
        "selections": [
            {
                k: getattr(row, k)
                for k in (
                    "id",
                    "output_id",
                    "revision",
                    "parent_version_id",
                    "provenance",
                    "actor_id",
                    "created_at",
                )
            }
            for row in db.scalars(
                versions.order_by(AudioSelectionVersion.revision.desc()).limit(limit).offset(offset)
            )
        ],
    }


def put_selection(db, project, tag, segment_id, body, actor):
    _, _, transcript = active_source(db, project, body, require_transcript=True)
    track = track_for(db, project, tag)
    segment = active_segment(db, project, transcript, segment_id)
    current = selection_for(db, project, track, segment)
    state = translation_state(db, project, track, segment)
    source = owned(db, SegmentRevision, project, segment.current_revision_id)
    if (
        (current.revision if current else 0) != body.revision
        or state is None
        or state.revision != body.translation_revision
        or body.expected_source_text_fingerprint != fingerprint(source.text)
    ):
        conflict()
    output = owned(db, NaturalOutput, project, body.output_id)
    inputs, *_ = inference_inputs(db, project, track, segment)
    if (
        output.track_id != track.id
        or output.segment_id != segment.id
        or output.input_fingerprint != fingerprint(inputs)
    ):
        conflict()
    from ..errors import APIError
    from .synthesis_cache import validate_output_evidence

    try:
        validate_output_evidence(db, project, output)
    except (APIError, ValueError, TypeError, KeyError, AttributeError):
        raise APIError(
            409, "AUDIO_EVIDENCE_INVALID", "Natural audio provenance requires review"
        ) from None
    select_output(db, project, track, segment, output, actor, "manual")
    return history(db, project, tag, segment_id)


def current_lines(db, project, tag, limit=100, offset=0):
    from ..models.execution import StageRun

    track = track_for(db, project, tag)
    state = source_state(db, project)
    if state is None or state.transcript_id is None:
        from ..errors import APIError

        raise APIError(
            409, "INPUT_REQUIRED", "Select source audio and finish transcription before synthesis"
        )
    transcript = owned(db, TranscriptRevision, project, state.transcript_id)
    query = active_segments_query(project, transcript.id)
    rows = db.scalars(query.limit(limit).offset(offset)).all()
    result = []
    for segment in rows:
        data = history(db, project, tag, segment.id, 1)
        work = db.scalars(
            scope(SynthesisLine, project)
            .join(StageRun, SynthesisLine.run_id == StageRun.id)
            .where(
                SynthesisLine.track_id == track.id,
                SynthesisLine.segment_id == segment.id,
                StageRun.status.in_(
                    (
                        "queued",
                        "running",
                        "retry_wait",
                        "failed",
                        "needs_review",
                        "stale",
                        "cancelling",
                    )
                ),
            )
            .order_by(SynthesisLine.created_at.desc())
            .limit(100)
        ).all()
        selected = (
            owned(db, NaturalOutput, project, data["selected_output_id"])
            if data["selected_output_id"]
            else None
        )
        from ..errors import APIError
        from .synthesis import reference_warnings, resolved_reference

        review, issues = None, []
        try:
            _, reference = resolved_reference(db, project, segment)
            warnings = reference_warnings(reference)
            review = {
                "version_id": reference.id,
                "duration_ms": reference.duration_ms,
                "warnings": warnings,
                "acknowledgement_required": bool(warnings),
            }
        except APIError as error:
            issues.append(error.code)
        result.append(
            {
                "segment_id": segment.id,
                "reference_review": review,
                "issues": issues,
                "selection_revision": data["selection_revision"],
                "selected": output_json(db, project, track, segment, selected)
                if selected
                else None,
                "outstanding": [
                    {
                        "line_id": x.id,
                        "run_id": x.run_id,
                        "status": owned(db, StageRun, project, x.run_id).status,
                    }
                    for x in work
                ],
            }
        )
    return {
        "items": result,
        "total": db.scalar(select(func.count()).select_from(query.subquery())),
        "acceptance": "not_assessed",
    }

"""Stable source lines and append-only corrections/split/merge lineage."""

from sqlalchemy import and_, func, or_, select

from ..execution.inputs import fingerprint, set_inputs
from ..models.core import new_id
from ..models.dubbing import (
    LanguageTrack,
    Segment,
    SegmentParent,
    SegmentRevision,
    TranslationRevision,
    TranslationState,
)
from .ownership import changed, check_revision, invalid, not_found, owned, owner, scope
from .source import active_source, new_transcript


def active_segment(db, project, transcript, segment_id):
    segment = owned(db, Segment, project, segment_id)
    if segment.archived or segment.transcript_id != transcript.id:
        not_found()
    return segment


def validate_fields(db, project, selection, values):
    if (
        not values["text"].strip()
        or not 0 <= values["start_ms"] < values["end_ms"] <= selection.end_ms - selection.start_ms
    ):
        invalid()
    if values["speaker_id"]:
        from .speakers import active_speaker

        active_speaker(db, project, values["speaker_id"], selection)


def revision_values(revision):
    return {key: getattr(revision, key) for key in ("text", "start_ms", "end_ms", "speaker_id")}


def active_segments_query(project, transcript_id):
    """Canonical visible order; stored display_index remains immutable creation lineage."""
    return (
        scope(Segment, project)
        .join(SegmentRevision, Segment.current_revision_id == SegmentRevision.id)
        .where(
            Segment.transcript_id == transcript_id,
            Segment.archived.is_(False),
            SegmentRevision.segment_id == Segment.id,
            SegmentRevision.project_id == project.id,
            SegmentRevision.workspace_id == project.workspace_id,
        )
        .order_by(SegmentRevision.start_ms, Segment.display_index, Segment.id)
    )


def segment_json(db, project, segment, *, window_start=0, position=None):
    revision = owned(db, SegmentRevision, project, segment.current_revision_id)
    if position is None and not segment.archived:
        before = (
            active_segments_query(project, segment.transcript_id)
            .order_by(None)
            .where(
                or_(
                    SegmentRevision.start_ms < revision.start_ms,
                    and_(
                        SegmentRevision.start_ms == revision.start_ms,
                        Segment.display_index < segment.display_index,
                    ),
                )
            )
        )
        position = db.scalar(select(func.count()).select_from(before.subquery()))
    parents = db.scalars(
        scope(SegmentParent, project)
        .where(SegmentParent.segment_id == segment.id)
        .order_by(SegmentParent.parent_segment_id)
    ).all()
    return {
        "id": segment.id,
        "revision": segment.revision,
        "revision_id": revision.id,
        "transcript_revision": segment.transcript_id,
        "display_index": position,
        "original_index": segment.display_index,
        "archived": segment.archived,
        "original_text": segment.original_text,
        "original_speaker_label": segment.original_speaker_label,
        "parent_segment_ids": [row.parent_segment_id for row in parents],
        "absolute_start_ms": window_start + revision.start_ms,
        "absolute_end_ms": window_start + revision.end_ms,
        "source_text_fingerprint": fingerprint(revision.text),
        **revision_values(revision),
    }


def append_revision(db, project, segment, values, actor, provenance, *, input_facets=None):
    previous = (
        owned(db, SegmentRevision, project, segment.current_revision_id)
        if segment.current_revision_id
        else None
    )
    if previous and revision_values(previous) == values:
        return False
    revision = SegmentRevision(
        id=new_id(),
        **owner(project),
        segment_id=segment.id,
        parent_revision_id=previous.id if previous else None,
        actor_id=actor,
        provenance=provenance,
        **values,
    )
    db.add(revision)
    db.flush()
    segment.current_revision_id = revision.id
    segment.revision += 1
    db.flush()
    facets = {}
    if previous is None or previous.text != revision.text:
        facets[f"segment.{segment.id}.text"] = fingerprint(revision.text)
        for state in db.scalars(
            scope(TranslationState, project).where(TranslationState.segment_id == segment.id)
        ):
            state.stale = True
            state.needs_review = True
            state.revision += 1
            target = owned(db, LanguageTrack, project, state.track_id)
            target_revision = owned(db, TranslationRevision, project, state.current_revision_id)
            facets[f"translation.{target.tag}.{segment.id}"] = {
                "text": fingerprint(target_revision.text),
                "source": fingerprint(revision.text),
                "stale": True,
            }
    if previous is None or (previous.start_ms, previous.end_ms) != (
        revision.start_ms,
        revision.end_ms,
    ):
        facets[f"segment.{segment.id}.timing"] = [revision.start_ms, revision.end_ms]
    if previous is None or previous.speaker_id != revision.speaker_id:
        facets[f"segment.{segment.id}.voice"] = revision.speaker_id
    if input_facets is None:
        set_inputs(db, project, facets)
    else:
        input_facets.update(facets)
    return True


def insert_segment(
    db,
    project,
    transcript,
    values,
    actor,
    provenance="manual",
    parents=(),
    label=None,
    *,
    input_facets=None,
    original_index=None,
):
    if original_index is None:
        last = db.scalar(
            select(func.max(Segment.display_index)).where(Segment.transcript_id == transcript.id)
        )
        original_index = 0 if last is None else last + 1
    segment = Segment(
        id=new_id(),
        **owner(project),
        transcript_id=transcript.id,
        display_index=original_index,
        original_text=values["text"],
        original_speaker_label=label,
        revision=0,
    )
    db.add(segment)
    db.flush()
    for parent_id in parents:
        db.add(SegmentParent(**owner(project), segment_id=segment.id, parent_segment_id=parent_id))
    append_revision(db, project, segment, values, actor, provenance, input_facets=input_facets)
    return segment


def create_segment(db, project, body, actor):
    state, selection, transcript = active_source(db, project, body)
    values = {k: getattr(body, k) for k in ("text", "start_ms", "end_ms", "speaker_id")}
    validate_fields(db, project, selection, values)
    if transcript is None:
        transcript = new_transcript(db, project, state, selection, actor, "manual")
    segment = insert_segment(db, project, transcript, values, actor)
    changed(
        db,
        project,
        "segment.created",
        count=1,
        segment_id=segment.id,
        transcript_id=transcript.id,
        provenance="manual",
    )
    return {
        "segment": segment_json(db, project, segment, window_start=selection.start_ms),
        "transcript_revision": transcript.id,
        "selection_revision": selection.revision,
    }


def patch_segment(db, project, segment_id, body, actor):
    _, selection, transcript = active_source(db, project, body, require_transcript=True)
    segment = active_segment(db, project, transcript, segment_id)
    check_revision(segment, body.revision)
    previous = owned(db, SegmentRevision, project, segment.current_revision_id)
    values = revision_values(previous) | body.model_dump(
        exclude_unset=True, exclude={"selection_revision", "transcript_revision", "revision"}
    )
    validate_fields(db, project, selection, values)
    if append_revision(db, project, segment, values, actor, "manual"):
        changed(
            db,
            project,
            "segment.edited",
            revision=segment.revision,
            segment_id=segment.id,
            provenance="manual",
        )
    return segment_json(db, project, segment, window_start=selection.start_ms)


def invalidate_segment(db, project, segment, *, input_facets=None):
    facets = {
        f"segment.{segment.id}.{kind}": {"historical": True} for kind in ("text", "timing", "voice")
    }
    for state in db.scalars(
        scope(TranslationState, project).where(TranslationState.segment_id == segment.id)
    ):
        state.stale = True
        state.needs_review = True
        state.revision += 1
        track = owned(db, LanguageTrack, project, state.track_id)
        facets[f"translation.{track.tag}.{segment.id}"] = {"historical": True}
    if input_facets is None:
        set_inputs(db, project, facets)
    else:
        input_facets.update(facets)


def archive_segment(db, project, segment):
    segment.archived = True
    invalidate_segment(db, project, segment)


def split_segment(db, project, segment_id, body, actor):
    _, selection, transcript = active_source(db, project, body, require_transcript=True)
    old = active_segment(db, project, transcript, segment_id)
    check_revision(old, body.revision)
    for part in body.parts:
        validate_fields(db, project, selection, part.model_dump())
    parts = [
        insert_segment(db, project, transcript, part.model_dump(), actor, "split", [old.id])
        for part in body.parts
    ]
    archive_segment(db, project, old)
    changed(db, project, "segment.split", count=len(parts), segment_id=old.id, provenance="split")
    return {
        "segments": [
            segment_json(db, project, row, window_start=selection.start_ms) for row in parts
        ]
    }


def merge_segments(db, project, body, actor):
    _, selection, transcript = active_source(db, project, body, require_transcript=True)
    if len({r.id for r in body.segments}) != len(body.segments):
        invalid()
    originals = []
    for row in body.segments:
        segment = active_segment(db, project, transcript, row.id)
        check_revision(segment, row.revision)
        originals.append(segment)
    values = {k: getattr(body, k) for k in ("text", "start_ms", "end_ms", "speaker_id")}
    validate_fields(db, project, selection, values)
    new = insert_segment(db, project, transcript, values, actor, "merge", [s.id for s in originals])
    for segment in originals:
        archive_segment(db, project, segment)
    changed(
        db, project, "segment.merged", count=len(originals), segment_id=new.id, provenance="merge"
    )
    return {"segment": segment_json(db, project, new, window_start=selection.start_ms)}

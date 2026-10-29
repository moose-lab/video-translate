"""Anonymous work labels, immutable label revisions, and atomic binding merges."""

from ..models.dubbing import Segment, SegmentRevision, Speaker, SpeakerRevision
from .ownership import changed, check_revision, invalid, not_found, owned, owner, scope
from .segments import append_revision, revision_values
from .source import active_source


def speaker_json(speaker):
    return {
        key: getattr(speaker, key)
        for key in ("id", "name", "description", "revision", "archived", "merged_into_id")
    }


def record_revision(db, project, speaker, actor):
    db.add(
        SpeakerRevision(
            **owner(project),
            speaker_id=speaker.id,
            actor_id=actor,
            **{
                key: getattr(speaker, key)
                for key in ("revision", "name", "description", "archived", "merged_into_id")
            },
        )
    )
    db.flush()


def create_speaker(db, project, body, actor):
    speaker = Speaker(**owner(project), **body.model_dump())
    db.add(speaker)
    db.flush()
    record_revision(db, project, speaker, actor)
    changed(db, project, "speaker.created", count=1, speaker_id=speaker.id)
    return speaker_json(speaker)


def patch_speaker(db, project, speaker_id, body, actor):
    speaker = owned(db, Speaker, project, speaker_id)
    if speaker.archived:
        not_found()
    check_revision(speaker, body.revision)
    values = body.model_dump(exclude_unset=True, exclude={"revision"})
    if values.get("archived"):
        # Existing current bindings cannot point at an archived work label.
        state, _, transcript = active_source_for_archive(db, project)
        if state and transcript:
            for segment in db.scalars(
                scope(Segment, project).where(
                    Segment.transcript_id == transcript.id, Segment.archived.is_(False)
                )
            ):
                revision = owned(db, SegmentRevision, project, segment.current_revision_id)
                if revision.speaker_id == speaker.id:
                    invalid()
    if any(getattr(speaker, k) != v for k, v in values.items()):
        for key, value in values.items():
            setattr(speaker, key, value)
        speaker.revision += 1
        record_revision(db, project, speaker, actor)
        changed(db, project, "speaker.edited", revision=speaker.revision, speaker_id=speaker.id)
    return speaker_json(speaker)


def active_source_for_archive(db, project):
    from ..models.dubbing import SourceSelection, TranscriptRevision
    from .source import source_state

    state = source_state(db, project)
    return (
        state,
        owned(db, SourceSelection, project, state.selection_id) if state else None,
        owned(db, TranscriptRevision, project, state.transcript_id)
        if state and state.transcript_id
        else None,
    )


def merge_speakers(db, project, body, actor):
    _, _, transcript = active_source(db, project, body, require_transcript=True)
    if body.source_id == body.target_id:
        invalid()
    source = owned(db, Speaker, project, body.source_id)
    target = owned(db, Speaker, project, body.target_id)
    if source.archived or target.archived:
        not_found()
    check_revision(source, body.source_revision)
    check_revision(target, body.target_revision)
    count = 0
    for segment in db.scalars(
        scope(Segment, project).where(
            Segment.transcript_id == transcript.id, Segment.archived.is_(False)
        )
    ):
        previous = owned(db, SegmentRevision, project, segment.current_revision_id)
        if previous.speaker_id == source.id:
            append_revision(
                db,
                project,
                segment,
                revision_values(previous) | {"speaker_id": target.id},
                actor,
                "speaker_merge",
            )
            count += 1
    source.archived = True
    source.merged_into_id = target.id
    source.revision += 1
    record_revision(db, project, source, actor)
    changed(
        db,
        project,
        "speaker.merged",
        count=count,
        revision=source.revision,
        speaker_id=source.id,
        merged_into_id=target.id,
    )
    return {"source": speaker_json(source), "target": speaker_json(target), "rebound_count": count}

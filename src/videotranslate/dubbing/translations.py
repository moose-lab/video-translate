"""Supplied immutable context and independent manual target cells; no inference."""

from ..execution.inputs import fingerprint, set_inputs
from ..languages.catalog import resolve
from ..models.core import new_id
from ..models.dubbing import (
    ContextRevision,
    LanguageTrack,
    SegmentRevision,
    TranslationRevision,
    TranslationState,
)
from .ownership import changed, check_revision, conflict, invalid, not_found, owned, owner, scope
from .segments import active_segment
from .source import active_source


def canonical_target(tag):
    try:
        result = resolve(tag)["tag"]
    except (ValueError, TypeError):
        invalid()
    if result == "auto":
        invalid()
    return result


def track_for(db, project, tag, *, active=True):
    row = db.scalar(scope(LanguageTrack, project).where(LanguageTrack.tag == canonical_target(tag)))
    if row is None or (active and row.archived):
        not_found()
    return row


def track_json(track):
    return {
        key: getattr(track, key)
        for key in ("id", "tag", "mode", "revision", "archived", "context_revision_id")
    } | {"materialized": True}


def context_snapshot(db, project, track, summary, glossary, actor):
    context = ContextRevision(
        id=new_id(),
        **owner(project),
        track_id=track.id,
        parent_revision_id=track.context_revision_id,
        summary=summary,
        glossary=glossary,
        actor_id=actor,
        provenance="supplied",
    )
    db.add(context)
    db.flush()
    track.context_revision_id = context.id
    db.flush()
    set_inputs(
        db,
        project,
        {
            f"target.{track.tag}.context": fingerprint(summary),
            f"target.{track.tag}.glossary": fingerprint(glossary),
        },
    )
    return context


def create_track(db, project, body, actor):
    if db.scalar(scope(LanguageTrack, project).where(LanguageTrack.tag == body.tag)):
        conflict()
    if body.tag not in project.target_languages and len(project.target_languages) >= 20:
        invalid()
    track = LanguageTrack(id=new_id(), **owner(project), tag=body.tag, mode=body.mode)
    db.add(track)
    db.flush()
    context_snapshot(db, project, track, body.summary, body.glossary, actor)
    if body.tag not in project.target_languages:
        project.target_languages = [*project.target_languages, body.tag]
    set_inputs(
        db, project, {f"target.{track.tag}.mode": track.mode, f"target.{track.tag}.active": True}
    )
    changed(
        db,
        project,
        "language_track.created",
        revision=track.revision,
        track_id=track.id,
        target_language=track.tag,
    )
    return track_json(track)


def patch_track(db, project, tag, body, actor):
    track = track_for(db, project, tag, active=False)
    if track.archived and body.archived is not False:
        not_found()
    check_revision(track, body.revision)
    context = owned(db, ContextRevision, project, track.context_revision_id)
    values = body.model_dump(exclude_unset=True, exclude={"revision"})
    summary, glossary = (
        values.get("summary", context.summary),
        values.get("glossary", context.glossary),
    )
    context_change = summary != context.summary or glossary != context.glossary
    other_change = any(getattr(track, k) != values[k] for k in ("mode", "archived") if k in values)
    if context_change or other_change:
        if context_change:
            context_snapshot(db, project, track, summary, glossary, actor)
        for key in ("mode", "archived"):
            if key in values:
                setattr(track, key, values[key])
        track.revision += 1
        project.target_languages = (
            [x for x in project.target_languages if x != track.tag]
            if track.archived
            else list(dict.fromkeys([*project.target_languages, track.tag]))
        )
        if len(project.target_languages) > 20:
            invalid()
        set_inputs(
            db,
            project,
            {
                f"target.{track.tag}.mode": track.mode,
                f"target.{track.tag}.active": not track.archived,
            },
        )
        changed(
            db,
            project,
            "language_track.edited",
            revision=track.revision,
            track_id=track.id,
            target_language=track.tag,
        )
    return track_json(track)


def translation_state(db, project, track, segment):
    return db.scalar(
        scope(TranslationState, project).where(
            TranslationState.track_id == track.id, TranslationState.segment_id == segment.id
        )
    )


def translation_json(db, project, state):
    revision = owned(db, TranslationRevision, project, state.current_revision_id)
    return {
        "revision": state.revision,
        "revision_id": revision.id,
        "text": revision.text,
        "locked": state.locked,
        "stale": state.stale,
        "needs_review": state.needs_review,
        "approved": revision.approved and not state.stale,
        "source_text_fingerprint": revision.source_text_fingerprint,
        "context_revision_id": revision.context_revision_id,
    }


def write_translation(
    db,
    project,
    track,
    segment,
    expected,
    text,
    actor,
    *,
    locked=None,
    approved=False,
    provenance="manual",
    force_locked=True,
):
    state = translation_state(db, project, track, segment)
    if (state.revision if state else 0) != expected:
        conflict()
    if state and state.locked and not force_locked:
        conflict()
    previous = owned(db, TranslationRevision, project, state.current_revision_id) if state else None
    previous_lock = state.locked if state else False
    source = owned(db, SegmentRevision, project, segment.current_revision_id)
    source_fp = fingerprint(source.text)
    lock = state.locked if state and locked is None else bool(locked)
    if (
        previous
        and previous.text == text
        and state.locked == lock
        and previous.approved == approved
        and previous.source_text_fingerprint == source_fp
        and not state.stale
        and previous.context_revision_id == track.context_revision_id
        and previous.mode == track.mode
    ):
        return state
    revision = TranslationRevision(
        id=new_id(),
        **owner(project),
        track_id=track.id,
        segment_id=segment.id,
        context_revision_id=track.context_revision_id,
        parent_revision_id=previous.id if previous else None,
        text=text,
        source_text_fingerprint=source_fp,
        mode=track.mode,
        provenance=provenance,
        approved=approved,
        actor_id=actor,
    )
    db.add(revision)
    db.flush()
    if state is None:
        state = TranslationState(
            **owner(project),
            segment_id=segment.id,
            track_id=track.id,
            current_revision_id=revision.id,
            revision=1,
            locked=lock,
            stale=False,
            needs_review=not approved,
        )
        db.add(state)
    else:
        state.current_revision_id = revision.id
        state.revision += 1
        state.locked = lock
        state.stale = False
        state.needs_review = not approved
    db.flush()
    set_inputs(
        db,
        project,
        {
            f"translation.{track.tag}.{segment.id}": {
                "text": fingerprint(text),
                "source": source_fp,
                "stale": False,
            }
        },
    )
    changed(
        db,
        project,
        "translation.reapproved" if provenance == "reapproval" else "translation.edited",
        revision=state.revision,
        fingerprint=source_fp,
        segment_id=segment.id,
        target_language=track.tag,
        provenance=provenance,
    )
    if locked is not None and lock != previous_lock:
        # Lock action is explicit; the immutable wording revision and cell state commit together.
        from ..execution.events import append_event

        append_event(
            db,
            project,
            "translation.lock_changed",
            facts={
                "revision": state.revision,
                "segment_id": segment.id,
                "target_language": track.tag,
            },
        )
    return state


def patch_translation(db, project, tag, segment_id, body, actor):
    _, _, transcript = active_source(db, project, body, require_transcript=True)
    track = track_for(db, project, tag)
    segment = active_segment(db, project, transcript, segment_id)
    state = write_translation(
        db,
        project,
        track,
        segment,
        body.revision,
        body.text,
        actor,
        locked=body.locked,
        approved=body.approved,
    )
    return translation_json(db, project, state)


def approve_translations(db, project, tag, body, actor):
    _, _, transcript = active_source(db, project, body, require_transcript=True)
    track = track_for(db, project, tag)
    if len({row.id for row in body.segments}) != len(body.segments):
        invalid()
    results = []
    for row in body.segments:
        segment = active_segment(db, project, transcript, row.id)
        state = translation_state(db, project, track, segment)
        if state is None:
            conflict()
        revision = owned(db, TranslationRevision, project, state.current_revision_id)
        state = write_translation(
            db,
            project,
            track,
            segment,
            row.revision,
            revision.text,
            actor,
            approved=True,
            provenance="reapproval",
        )
        results.append({"segment_id": segment.id, **translation_json(db, project, state)})
    return {"items": results}


def align_declared_tracks(db, project):
    """Legacy project target edits retain existing configs/history and arbitrate track CAS."""
    values = {}
    for track in db.scalars(scope(LanguageTrack, project)):
        archived = track.tag not in project.target_languages
        if track.archived != archived:
            track.archived = archived
            track.revision += 1
            values[f"target.{track.tag}.active"] = not archived
    if values:
        set_inputs(db, project, values)

"""Bounded current timeline and safe read-only histories."""

from sqlalchemy import func, select

from ..models.dubbing import (
    ContextRevision,
    LanguageTrack,
    Segment,
    SegmentRevision,
    SourceSelection,
    Speaker,
    TranscriptRevision,
    TranslationRevision,
    TranslationState,
)
from .ownership import owned, scope
from .segments import segment_json
from .source import selection_current, selection_json, source_state
from .speakers import speaker_json
from .translations import canonical_target, track_json, translation_json


def paged(db, query, model, limit, offset):
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.scalars(query.order_by(model.created_at, model.id).limit(limit).offset(offset)).all()
    return rows, total


def timeline(db, project, tag, limit, offset):
    tag = canonical_target(tag) if tag else None
    state = source_state(db, project)
    selection = owned(db, SourceSelection, project, state.selection_id) if state else None
    transcript = (
        owned(db, TranscriptRevision, project, state.transcript_id)
        if state and state.transcript_id
        else None
    )
    stale = bool(
        transcript
        and (
            transcript.selection_id != selection.id or not selection_current(db, project, selection)
        )
    )
    query = scope(Segment, project).where(
        Segment.transcript_id == (transcript.id if transcript else ""), Segment.archived.is_(False)
    )
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.scalars(
        query.order_by(Segment.display_index, Segment.id).limit(limit).offset(offset)
    ).all()
    track = (
        db.scalar(scope(LanguageTrack, project).where(LanguageTrack.tag == tag)) if tag else None
    )
    # Historical segment absolute times use the transcript's own selection, never a new window.
    lineage_selection = (
        owned(db, SourceSelection, project, transcript.selection_id) if transcript else selection
    )
    segments = []
    for segment in rows:
        data = segment_json(db, project, segment, window_start=lineage_selection.start_ms)
        if track:
            cell = db.scalar(
                scope(TranslationState, project).where(
                    TranslationState.track_id == track.id, TranslationState.segment_id == segment.id
                )
            )
            data["translation"] = translation_json(db, project, cell) if cell else None
            if stale and data["translation"]:
                data["translation"]["stale"] = True
                data["translation"]["approved"] = False
        else:
            data["translation"] = None
        segments.append(data)
    track_query = scope(LanguageTrack, project)
    track_total = db.scalar(select(func.count()).select_from(track_query.subquery()))
    tracks = db.scalars(
        track_query.order_by(LanguageTrack.archived, LanguageTrack.tag).limit(200)
    ).all()
    summaries = [track_json(row) for row in tracks]
    actual = set(
        db.scalars(
            select(LanguageTrack.tag).where(
                LanguageTrack.project_id == project.id,
                LanguageTrack.workspace_id == project.workspace_id,
                LanguageTrack.tag.in_(project.target_languages),
            )
        )
    )
    summaries += [
        {
            "tag": declared,
            "materialized": False,
            "archived": False,
            "mode": "Fast",
            "revision": 0,
            "context_revision_id": None,
        }
        for declared in project.target_languages
        if declared not in actual
    ]
    speaker_query = scope(Speaker, project).where(Speaker.archived.is_(False))
    cast_total = db.scalar(select(func.count()).select_from(speaker_query.subquery()))
    cast = db.scalars(speaker_query.order_by(Speaker.created_at, Speaker.id).limit(200)).all()
    return {
        "project_id": project.id,
        "project_revision": project.revision,
        "source": selection_json(db, project, selection) if selection else None,
        "transcript": (
            {
                "id": transcript.id,
                "selection_id": transcript.selection_id,
                "provenance": transcript.provenance,
                "parent_revision_id": transcript.parent_revision_id,
                "stale": stale,
            }
            if transcript
            else None
        ),
        "segments": segments,
        "total": total,
        "limit": limit,
        "offset": offset,
        "target_language": tag,
        "language_tracks": sorted(summaries, key=lambda row: (row["archived"], row["tag"]))[:200],
        "language_tracks_total": track_total
        + len([tag for tag in project.target_languages if tag not in actual]),
        "cast": [speaker_json(row) for row in cast],
        "cast_total": cast_total,
        "references": {"items": [], "total": 0, "available": False},
    }


def revision_json(row):
    # Explicit public history fields. No source storage keys or provider payloads.
    fields = {
        SegmentRevision: (
            "id",
            "segment_id",
            "parent_revision_id",
            "text",
            "start_ms",
            "end_ms",
            "speaker_id",
            "provenance",
            "actor_id",
            "created_at",
        ),
        TranslationRevision: (
            "id",
            "segment_id",
            "track_id",
            "parent_revision_id",
            "context_revision_id",
            "text",
            "source_text_fingerprint",
            "mode",
            "provenance",
            "approved",
            "actor_id",
            "created_at",
        ),
        ContextRevision: (
            "id",
            "track_id",
            "parent_revision_id",
            "summary",
            "glossary",
            "provenance",
            "created_at",
        ),
        TranscriptRevision: (
            "id",
            "selection_id",
            "parent_revision_id",
            "provenance",
            "actor_id",
            "run_id",
            "created_at",
        ),
    }
    return {key: getattr(row, key) for key in fields[type(row)]}

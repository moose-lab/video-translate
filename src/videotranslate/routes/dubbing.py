"""Session/CSRF-scoped manual dubbing domain API. Remote jobs arrive in later increments."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from fastapi.routing import APIRoute
from sqlalchemy.orm import Session

from ..db import get_db
from ..dubbing import contracts as c
from ..dubbing import imports, segments, source, speakers, timeline, translations
from ..dubbing.ownership import owned, project_for, scope
from ..errors import APIError
from ..models.dubbing import (
    ContextRevision,
    LanguageTrack,
    Segment,
    SegmentRevision,
    SourceSelection,
    Speaker,
    SpeakerRevision,
    TranscriptRevision,
    TranslationRevision,
)
from ..security import Identity, require_csrf, require_identity


class BoundedDubbingRoute(APIRoute):
    """Bound the JSON envelope while streaming, before Pydantic or JSON decoding."""

    def get_route_handler(self):
        handler = super().get_route_handler()

        async def bounded(request: Request):
            if request.method in {"POST", "PUT", "PATCH"}:
                chunks, total = [], 0
                async for chunk in request.stream():
                    total += len(chunk)
                    if total > 4 * 1024 * 1024:
                        raise APIError(422, "INVALID_EDIT", "Request exceeds editing limit")
                    chunks.append(chunk)
                request._body = b"".join(chunks)
            return await handler(request)

        return bounded


router = APIRouter(
    prefix="/projects/{project_id}", tags=["dubbing"], route_class=BoundedDubbingRoute
)
Limit = Annotated[int, Query(ge=1, le=200)]
Offset = Annotated[int, Query(ge=0, le=10000000)]


def mutation(db, identity, project_id, function, *args):
    project = project_for(db, identity, project_id, write=True)
    result = function(db, project, *args, identity.user.id)
    db.commit()
    return result


@router.put("/source-selection")
def put_selection(
    project_id: str,
    body: c.SelectionPut,
    identity: Identity = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    return mutation(db, identity, project_id, source.select_source, body)


@router.get("/timeline")
def get_timeline(
    project_id: str,
    target_language: Annotated[str | None, Query(max_length=40)] = None,
    limit: Limit = 100,
    offset: Offset = 0,
    identity: Identity = Depends(require_identity),
    db: Session = Depends(get_db),
):
    return timeline.timeline(
        db, project_for(db, identity, project_id), target_language, limit, offset
    )


@router.post("/segments", status_code=201)
def post_segment(
    project_id: str,
    body: c.SegmentCreate,
    identity: Identity = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    return mutation(db, identity, project_id, segments.create_segment, body)


@router.patch("/segments/{segment_id}")
def edit_segment(
    project_id: str,
    segment_id: str,
    body: c.SegmentPatch,
    identity: Identity = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    return mutation(db, identity, project_id, segments.patch_segment, segment_id, body)


@router.post("/segments/{segment_id}/split", status_code=201)
def split_segment(
    project_id: str,
    segment_id: str,
    body: c.SegmentSplit,
    identity: Identity = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    return mutation(db, identity, project_id, segments.split_segment, segment_id, body)


@router.post("/segments/merge", status_code=201)
def merge_segments(
    project_id: str,
    body: c.SegmentMerge,
    identity: Identity = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    return mutation(db, identity, project_id, segments.merge_segments, body)


@router.post("/speakers", status_code=201)
def post_speaker(
    project_id: str,
    body: c.SpeakerCreate,
    identity: Identity = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    return mutation(db, identity, project_id, speakers.create_speaker, body)


@router.patch("/speakers/{speaker_id}")
def edit_speaker(
    project_id: str,
    speaker_id: str,
    body: c.SpeakerPatch,
    identity: Identity = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    return mutation(db, identity, project_id, speakers.patch_speaker, speaker_id, body)


@router.post("/speakers/merge")
def merge_speakers(
    project_id: str,
    body: c.SpeakerMerge,
    identity: Identity = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    return mutation(db, identity, project_id, speakers.merge_speakers, body)


@router.post("/language-tracks", status_code=201)
def post_track(
    project_id: str,
    body: c.TrackCreate,
    identity: Identity = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    return mutation(db, identity, project_id, translations.create_track, body)


@router.patch("/language-tracks/{tag}")
def edit_track(
    project_id: str,
    tag: str,
    body: c.TrackPatch,
    identity: Identity = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    return mutation(db, identity, project_id, translations.patch_track, tag, body)


@router.patch("/language-tracks/{tag}/segments/{segment_id}")
def edit_translation(
    project_id: str,
    tag: str,
    segment_id: str,
    body: c.TranslationPatch,
    identity: Identity = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    return mutation(db, identity, project_id, translations.patch_translation, tag, segment_id, body)


@router.post("/language-tracks/{tag}/approve")
def approve_track(
    project_id: str,
    tag: str,
    body: c.Approve,
    identity: Identity = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    return mutation(db, identity, project_id, translations.approve_translations, tag, body)


@router.post("/source/import/preview")
def preview_source(
    project_id: str,
    body: c.ImportPreview,
    identity: Identity = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    return imports.preview_import(db, project_for(db, identity, project_id), body)


@router.post("/source/import/apply", status_code=201)
def apply_source(
    project_id: str,
    body: c.ImportApply,
    identity: Identity = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    return mutation(db, identity, project_id, imports.apply_import, body)


@router.post("/language-tracks/{tag}/import/preview")
def preview_target(
    project_id: str,
    tag: str,
    body: c.ImportPreview,
    identity: Identity = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    return imports.preview_import(db, project_for(db, identity, project_id), body, tag)


@router.post("/language-tracks/{tag}/import/apply")
def apply_target(
    project_id: str,
    tag: str,
    body: c.ImportApply,
    identity: Identity = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    project = project_for(db, identity, project_id, write=True)
    result = imports.apply_import(db, project, body, identity.user.id, tag)
    db.commit()
    return result


@router.get("/source-selections")
def selection_history(
    project_id: str,
    limit: Limit = 100,
    offset: Offset = 0,
    identity: Identity = Depends(require_identity),
    db: Session = Depends(get_db),
):
    project = project_for(db, identity, project_id)
    rows, total = timeline.paged(
        db, scope(SourceSelection, project), SourceSelection, limit, offset
    )
    return {"items": [source.selection_json(db, project, row) for row in rows], "total": total}


@router.get("/transcripts")
def transcript_history(
    project_id: str,
    limit: Limit = 100,
    offset: Offset = 0,
    identity: Identity = Depends(require_identity),
    db: Session = Depends(get_db),
):
    project = project_for(db, identity, project_id)
    rows, total = timeline.paged(
        db, scope(TranscriptRevision, project), TranscriptRevision, limit, offset
    )
    return {"items": [timeline.revision_json(row) for row in rows], "total": total}


@router.get("/transcripts/{transcript_id}/segments")
def historical_segments(
    project_id: str,
    transcript_id: str,
    limit: Limit = 100,
    offset: Offset = 0,
    identity: Identity = Depends(require_identity),
    db: Session = Depends(get_db),
):
    project = project_for(db, identity, project_id)
    transcript = owned(db, TranscriptRevision, project, transcript_id)
    selection = owned(db, SourceSelection, project, transcript.selection_id)
    query = scope(Segment, project).where(Segment.transcript_id == transcript.id)
    rows, total = timeline.paged(db, query, Segment, limit, offset)
    return {
        "items": [
            segments.segment_json(db, project, row, window_start=selection.start_ms) for row in rows
        ],
        "total": total,
    }


@router.get("/segments/{segment_id}/revisions")
def segment_history(
    project_id: str,
    segment_id: str,
    limit: Limit = 100,
    offset: Offset = 0,
    identity: Identity = Depends(require_identity),
    db: Session = Depends(get_db),
):
    project = project_for(db, identity, project_id)
    owned(db, Segment, project, segment_id)
    rows, total = timeline.paged(
        db,
        scope(SegmentRevision, project).where(SegmentRevision.segment_id == segment_id),
        SegmentRevision,
        limit,
        offset,
    )
    return {"items": [timeline.revision_json(row) for row in rows], "total": total}


@router.get("/speakers/{speaker_id}/revisions")
def speaker_history(
    project_id: str,
    speaker_id: str,
    limit: Limit = 100,
    offset: Offset = 0,
    identity: Identity = Depends(require_identity),
    db: Session = Depends(get_db),
):
    project = project_for(db, identity, project_id)
    owned(db, Speaker, project, speaker_id)
    rows, total = timeline.paged(
        db,
        scope(SpeakerRevision, project).where(SpeakerRevision.speaker_id == speaker_id),
        SpeakerRevision,
        limit,
        offset,
    )
    return {
        "items": [
            {
                key: getattr(row, key)
                for key in (
                    "id",
                    "revision",
                    "name",
                    "description",
                    "archived",
                    "merged_into_id",
                    "actor_id",
                    "created_at",
                )
            }
            for row in rows
        ],
        "total": total,
    }


@router.get("/language-tracks/{tag}/contexts")
def context_history(
    project_id: str,
    tag: str,
    limit: Limit = 100,
    offset: Offset = 0,
    identity: Identity = Depends(require_identity),
    db: Session = Depends(get_db),
):
    project = project_for(db, identity, project_id)
    track = translations.track_for(db, project, tag, active=False)
    rows, total = timeline.paged(
        db,
        scope(ContextRevision, project).where(ContextRevision.track_id == track.id),
        ContextRevision,
        limit,
        offset,
    )
    return {"items": [timeline.revision_json(row) for row in rows], "total": total}


@router.get("/language-tracks/{tag}/segments/{segment_id}/revisions")
def translation_history(
    project_id: str,
    tag: str,
    segment_id: str,
    limit: Limit = 100,
    offset: Offset = 0,
    identity: Identity = Depends(require_identity),
    db: Session = Depends(get_db),
):
    project = project_for(db, identity, project_id)
    track = translations.track_for(db, project, tag, active=False)
    owned(db, Segment, project, segment_id)
    query = scope(TranslationRevision, project).where(
        TranslationRevision.track_id == track.id, TranslationRevision.segment_id == segment_id
    )
    rows, total = timeline.paged(db, query, TranslationRevision, limit, offset)
    return {"items": [timeline.revision_json(row) for row in rows], "total": total}


@router.get("/speakers")
def list_speakers(
    project_id: str,
    limit: Limit = 100,
    offset: Offset = 0,
    include_archived: bool = False,
    include_historical: bool = False,
    identity: Identity = Depends(require_identity),
    db: Session = Depends(get_db),
):
    project = project_for(db, identity, project_id)
    query = speakers.speakers_query(
        db, project, include_archived=include_archived, include_historical=include_historical
    )
    rows, total = timeline.paged(db, query, Speaker, limit, offset)
    return {"items": [speakers.speaker_json(row) for row in rows], "total": total}


@router.get("/language-tracks")
def list_tracks(
    project_id: str,
    limit: Limit = 100,
    offset: Offset = 0,
    identity: Identity = Depends(require_identity),
    db: Session = Depends(get_db),
):
    project = project_for(db, identity, project_id)
    rows, total = timeline.paged(db, scope(LanguageTrack, project), LanguageTrack, limit, offset)
    return {"items": [translations.track_json(row) for row in rows], "total": total}

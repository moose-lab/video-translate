"""Owned CSRF-protected natural audio commands and bounded private reads."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..db import get_db
from ..dubbing import synthesis, synthesis_outputs, synthesis_settings
from ..dubbing.ownership import owned, project_for
from ..dubbing.synthesis_contracts import AudioSelectionPut, Synthesize, VoiceSettingsPut
from ..dubbing.translations import track_for
from ..errors import APIError
from ..models.synthesis import SynthesisCommand
from ..security import Identity, require_csrf, require_identity
from .dubbing import BoundedDubbingRoute

router = APIRouter(
    prefix="/projects/{project_id}/language-tracks/{tag}",
    tags=["synthesis"],
    route_class=BoundedDubbingRoute,
)
Limit = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0, le=10000000)]


@router.post("/synthesize", status_code=202)
def post_synthesize(
    project_id: str,
    tag: str,
    body: Synthesize,
    identity: Identity = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    result = synthesis.command(
        db, project_for(db, identity, project_id, write=True), tag, body, identity.user.id
    )
    db.commit()
    return result


@router.get("/synthesis")
def get_synthesis(
    project_id: str,
    tag: str,
    limit: Limit = 100,
    offset: Offset = 0,
    identity: Identity = Depends(require_identity),
    db: Session = Depends(get_db),
):
    return synthesis_outputs.current_lines(
        db, project_for(db, identity, project_id), tag, limit, offset
    )


@router.get("/synthesis/{request_id}")
def get_command(
    project_id: str,
    tag: str,
    request_id: str,
    limit: Limit = 100,
    offset: Offset = 0,
    identity: Identity = Depends(require_identity),
    db: Session = Depends(get_db),
):
    project = project_for(db, identity, project_id)
    intent = owned(db, SynthesisCommand, project, request_id)
    if intent.track_id != track_for(db, project, tag, active=False).id:
        raise APIError(404, "NOT_FOUND", "Resource not found")
    return synthesis.command_json(db, project, intent, limit, offset)


@router.get("/segments/{segment_id}/audio-history")
def get_history(
    project_id: str,
    tag: str,
    segment_id: str,
    limit: Limit = 100,
    offset: Offset = 0,
    identity: Identity = Depends(require_identity),
    db: Session = Depends(get_db),
):
    return synthesis_outputs.history(
        db, project_for(db, identity, project_id), tag, segment_id, limit, offset
    )


@router.put("/segments/{segment_id}/audio-selection")
def put_selection(
    project_id: str,
    tag: str,
    segment_id: str,
    body: AudioSelectionPut,
    identity: Identity = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    result = synthesis_outputs.put_selection(
        db,
        project_for(db, identity, project_id, write=True),
        tag,
        segment_id,
        body,
        identity.user.id,
    )
    db.commit()
    return result


@router.get("/voice-settings")
@router.get("/segments/{segment_id}/voice-settings")
def get_settings(
    project_id: str,
    tag: str,
    segment_id: str | None = None,
    limit: Limit = 100,
    offset: Offset = 0,
    identity: Identity = Depends(require_identity),
    db: Session = Depends(get_db),
):
    project = project_for(db, identity, project_id)
    if segment_id:
        from ..models.dubbing import Segment

        owned(db, Segment, project, segment_id)
    return synthesis_settings.settings_json(
        db, project, track_for(db, project, tag), segment_id, limit, offset
    )


@router.put("/voice-settings")
@router.put("/segments/{segment_id}/voice-settings")
def put_settings(
    project_id: str,
    tag: str,
    body: VoiceSettingsPut,
    segment_id: str | None = None,
    identity: Identity = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    result = synthesis_settings.put_settings(
        db,
        project_for(db, identity, project_id, write=True),
        tag,
        segment_id,
        body,
        identity.user.id,
    )
    db.commit()
    return result

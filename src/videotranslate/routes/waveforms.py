"""Guarded CPU waveform command and pure owned preview reads."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from ..db import get_db
from ..dubbing import waveforms
from ..dubbing.ownership import project_for
from ..dubbing.waveforms_contracts import WaveformCreate
from ..dubbing.waveforms_execution import read_artifact
from ..security import Identity, require_csrf, require_identity
from .dubbing import BoundedDubbingRoute

router = APIRouter(
    prefix="/projects/{project_id}/waveforms", tags=["waveforms"], route_class=BoundedDubbingRoute
)


@router.post("", status_code=202)
def create(
    project_id: str,
    body: WaveformCreate,
    identity: Identity = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    project = project_for(db, identity, project_id, write=True)
    run = waveforms.admit(db, project, body)
    run_id = run.id
    db.commit()
    db.expire_all()
    project = project_for(db, identity, project_id)
    return waveforms.summary(db, project, waveforms.owned_waveform(db, project, run_id))[0]


@router.get("")
def list_waveforms(
    project_id: str,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
    offset: Annotated[int, Query(ge=0, le=10000000)] = 0,
    identity: Identity = Depends(require_identity),
    db: Session = Depends(get_db),
):
    return waveforms.discovery(db, project_for(db, identity, project_id), limit, offset)


@router.get("/{run_id}")
def detail(
    project_id: str,
    run_id: str,
    request: Request,
    identity: Identity = Depends(require_identity),
    db: Session = Depends(get_db),
):
    project = project_for(db, identity, project_id)
    run = waveforms.owned_waveform(db, project, run_id)
    result, asset = waveforms.summary(db, project, run)
    options = dict(run.options)
    if asset:
        # Detach byte proof before closing the read transaction; storage may be remote.
        from types import SimpleNamespace

        proof = SimpleNamespace(
            storage_key=asset.storage_key, byte_size=asset.byte_size, sha256=asset.sha256
        )
        db.rollback()
        try:
            result["waveform"] = read_artifact(request.app.state.storage, proof, options)
        except (ValueError, TypeError, KeyError, AttributeError, OSError):
            result.update(artifact=None, waveform=None, error={"code": "WAVEFORM_ARTIFACT_INVALID"})
    return result

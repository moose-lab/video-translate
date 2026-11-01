"""Private source URL commands; GET never dispatches downloads."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from ..db import get_db
from ..dubbing import source_imports
from ..dubbing.ownership import owned, project_for
from ..dubbing.source_imports import SourceImportCreate
from ..models.source_import import SourceImport
from ..security import Identity, require_csrf, require_identity
from .dubbing import BoundedDubbingRoute

router = APIRouter(
    prefix="/projects/{project_id}/source-imports",
    tags=["source-imports"],
    route_class=BoundedDubbingRoute,
)


@router.post("", status_code=202)
def start(
    project_id: str,
    body: SourceImportCreate,
    request: Request,
    identity: Identity = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    result = source_imports.start(
        db,
        project_for(db, identity, project_id, write=True),
        body,
        identity.user.id,
        request.app.state.settings,
    )
    db.commit()
    return result


@router.get("")
def listing(
    project_id: str,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0, le=10000000)] = 0,
    identity: Identity = Depends(require_identity),
    db: Session = Depends(get_db),
):
    return source_imports.listing(db, project_for(db, identity, project_id), limit, offset)


@router.get("/{import_id}")
def detail(
    project_id: str,
    import_id: str,
    identity: Identity = Depends(require_identity),
    db: Session = Depends(get_db),
):
    project = project_for(db, identity, project_id)
    return source_imports.detail(db, project, owned(db, SourceImport, project, import_id))

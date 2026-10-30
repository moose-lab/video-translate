"""Guarded project-owned fit plan and settings APIs."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..db import get_db
from ..dubbing import fit_plans, fit_settings
from ..dubbing.fit_contracts import FitPlanCreate, FitSettingsPut
from ..dubbing.ownership import project_for
from ..security import Identity, require_csrf, require_identity
from .dubbing import BoundedDubbingRoute

router = APIRouter(
    prefix="/projects/{project_id}", tags=["finishing"], route_class=BoundedDubbingRoute
)
Limit = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0, le=10000000)]


@router.get("/fit-settings")
def get_settings(
    project_id: str,
    limit: Limit = 100,
    offset: Offset = 0,
    identity: Identity = Depends(require_identity),
    db: Session = Depends(get_db),
):
    return fit_settings.settings_json(db, project_for(db, identity, project_id), limit, offset)


@router.put("/fit-settings")
def put_settings(
    project_id: str,
    body: FitSettingsPut,
    identity: Identity = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    result = fit_settings.put_settings(
        db, project_for(db, identity, project_id, write=True), body, identity.user.id
    )
    db.commit()
    return result


@router.post("/fit-plans", status_code=202)
def post_plan(
    project_id: str,
    body: FitPlanCreate,
    identity: Identity = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    result = fit_plans.command(
        db, project_for(db, identity, project_id, write=True), body, identity.user.id
    )
    db.commit()
    return result


@router.get("/fit-plans")
def get_plans(
    project_id: str,
    limit: Limit = 100,
    offset: Offset = 0,
    identity: Identity = Depends(require_identity),
    db: Session = Depends(get_db),
):
    return fit_plans.summaries(db, project_for(db, identity, project_id), limit, offset)


@router.get("/fit-plans/{plan_id}")
def get_plan(
    project_id: str,
    plan_id: str,
    limit: Limit = 100,
    offset: Offset = 0,
    identity: Identity = Depends(require_identity),
    db: Session = Depends(get_db),
):
    from ..dubbing.ownership import owned
    from ..models.finishing import FitPlanCommand

    project = project_for(db, identity, project_id)
    return fit_plans.detail(db, project, owned(db, FitPlanCommand, project, plan_id), limit, offset)

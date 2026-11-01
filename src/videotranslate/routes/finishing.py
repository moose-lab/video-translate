"""Guarded project-owned fit plan and settings APIs."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..db import get_db
from ..dubbing import fit_plans, fit_settings
from ..dubbing.fit_contracts import FitPlanCreate, FitSettingsPut
from ..dubbing.ownership import owned, project_for
from ..models.finishing import FitPlanCommand
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
    admitted = fit_plans.command(
        db, project_for(db, identity, project_id, write=True), body, identity.user.id
    )
    db.commit()
    # Admission remains atomic. Response proofs must neither extend its write lock
    # nor reuse the pre-commit editor heads after another writer gets that lock.
    db.expire_all()
    project = project_for(db, identity, project_id)
    intent = owned(db, FitPlanCommand, project, admitted.id)
    return fit_plans.detail(db, project, intent, reused=admitted.reused)


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
    project = project_for(db, identity, project_id)
    return fit_plans.detail(db, project, owned(db, FitPlanCommand, project, plan_id), limit, offset)


from ..dubbing import deliveries  # noqa: E402
from ..dubbing.delivery_contracts import DeliveryCreate  # noqa: E402
from ..models.delivery import DeliveryCommand  # noqa: E402


@router.post("/deliveries", status_code=202)
def post_delivery(
    project_id: str,
    body: DeliveryCreate,
    identity: Identity = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    project = project_for(db, identity, project_id)
    parent = owned(db, FitPlanCommand, project, body.fit_plan_id)
    validated_capture = deliveries.valid_parent(db, project, parent)
    db.commit()
    db.expire_all()
    project = project_for(db, identity, project_id, write=True)
    delivery_id = deliveries.admit(db, project, body, identity.user.id, validated_capture)
    db.commit()
    db.expire_all()
    project = project_for(db, identity, project_id)
    return deliveries.detail(db, project, owned(db, DeliveryCommand, project, delivery_id))


@router.get("/deliveries")
def get_deliveries(
    project_id: str,
    limit: Limit = 100,
    offset: Offset = 0,
    identity: Identity = Depends(require_identity),
    db: Session = Depends(get_db),
):
    return deliveries.summaries(db, project_for(db, identity, project_id), limit, offset)


@router.get("/deliveries/{delivery_id}")
def get_delivery(
    project_id: str,
    delivery_id: str,
    identity: Identity = Depends(require_identity),
    db: Session = Depends(get_db),
):
    project = project_for(db, identity, project_id)
    return deliveries.detail(db, project, owned(db, DeliveryCommand, project, delivery_id))


@router.get("/deliveries/{delivery_id}/artifacts")
def get_delivery_artifacts(
    project_id: str,
    delivery_id: str,
    identity: Identity = Depends(require_identity),
    db: Session = Depends(get_db),
):
    project = project_for(db, identity, project_id)
    detail = deliveries.detail(db, project, owned(db, DeliveryCommand, project, delivery_id))
    return dict(
        items=detail["artifacts"],
        total=len(detail["artifacts"]),
        current=detail["current"],
        manifest_valid=detail["manifest_valid"],
    )

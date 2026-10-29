"""Authorized project journal reads."""

import asyncio
import json
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from ..db import get_db
from ..errors import APIError
from ..execution.events import event_json
from ..models.execution import ProjectEvent
from ..security import Identity, require_identity
from .projects import owned_project

router = APIRouter(tags=["events"])


def event_page(db, workspace_id, project_id, after, limit):
    owned_project(db, workspace_id, project_id)
    query = select(ProjectEvent).where(
        ProjectEvent.workspace_id == workspace_id,
        ProjectEvent.project_id == project_id,
        ProjectEvent.sequence > after,
    )
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.scalars(query.order_by(ProjectEvent.sequence).limit(limit)).all()
    return {
        "items": [event_json(row) for row in rows],
        "total": total,
        "next_cursor": rows[-1].sequence if rows else after,
    }


@router.get("/projects/{project_id}/events")
def list_events(
    project_id: str,
    after: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    identity: Identity = Depends(require_identity),
    db: Session = Depends(get_db),
):
    return event_page(db, identity.workspace.id, project_id, after, limit)


@router.get("/projects/{project_id}/events/stream")
def stream_events(
    project_id: str,
    request: Request,
    after: Annotated[int, Query(ge=0)] = 0,
    follow: bool = True,
    last_event_id: Annotated[str | None, Header()] = None,
    identity: Identity = Depends(require_identity),
    db: Session = Depends(get_db),
):
    if last_event_id is not None:
        if not last_event_id.isascii() or not last_event_id.isdecimal() or len(last_event_id) > 18:
            raise APIError(400, "INVALID_CURSOR", "Invalid event cursor")
        after = max(after, int(last_event_id))
    owned_project(db, identity.workspace.id, project_id)
    db.rollback()
    session_factory = request.app.state.session_factory

    def fetch_page(cursor):
        # The session and all synchronous database operations stay in this worker
        # thread; close its transaction before the generator yields or sleeps.
        with session_factory() as fresh:
            current = require_identity(request, fresh)
            return event_page(fresh, current.workspace.id, project_id, cursor, 200)

    async def stream():
        cursor = after
        while True:
            try:
                page = await run_in_threadpool(fetch_page, cursor)
            except APIError:
                return
            for event in page["items"]:
                cursor = event["sequence"]
                data = json.dumps(jsonable_encoder(event), separators=(",", ":"))
                yield f"id: {cursor}\nevent: project_event\ndata: {data}\n\n"
            if len(page["items"]) == 200:
                continue
            if not follow:
                return
            yield ": heartbeat\n\n"
            await asyncio.sleep(2)

    return StreamingResponse(
        stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"}
    )

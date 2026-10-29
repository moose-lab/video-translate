import json

import pytest


def test_stream_drains_and_resumes_after_greater_cursor(execution_project):
    client, _, project = execution_project
    path = f"/api/projects/{project['id']}/events"
    events = client.get(path).json()["items"]
    assert len(events) >= 1
    first = events[0]["sequence"]
    response = client.get(
        path + "/stream",
        params={"follow": "false", "after": 0},
        headers={"Last-Event-ID": str(first)},
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    ids = [int(line[4:].strip()) for line in response.text.splitlines() if line.startswith("id:")]
    assert ids == [e["sequence"] for e in events if e["sequence"] > first]
    for line in response.text.splitlines():
        if line.startswith("data:"):
            json.loads(line[5:])
    assert (
        client.get(path + "/stream?follow=false", headers={"Last-Event-ID": "-1"}).status_code
        == 400
    )


@pytest.mark.parametrize("reason", ["expiry", "revocation", "project_deletion"])
def test_stream_rechecks_authorization_between_polls(execution_project, monkeypatch, reason):
    import asyncio
    from datetime import timedelta

    from starlette.requests import Request

    from videotranslate.models.core import AuthSession, Project, utcnow
    from videotranslate.routes.events import stream_events
    from videotranslate.security import require_identity

    client, _, project = execution_project
    app = client.app
    cookie = "; ".join(f"{k}={v}" for k, v in client.cookies.items()).encode()
    request = Request(
        {"type": "http", "method": "GET", "path": "/", "headers": [(b"cookie", cookie)], "app": app}
    )
    with app.state.session_factory() as db:
        identity = require_identity(request, db)
        response = stream_events(project["id"], request, 0, True, None, identity, db)
        session_id = identity.session.id

    async def no_wait(_):
        pass

    monkeypatch.setattr("videotranslate.routes.events.asyncio.sleep", no_wait)

    async def read():
        iterator = response.body_iterator
        while True:
            value = await anext(iterator)
            if value.startswith(": heartbeat"):
                break
        with app.state.session_factory.begin() as db:
            if reason == "expiry":
                db.get(AuthSession, session_id).expires_at = utcnow() - timedelta(seconds=1)
            elif reason == "revocation":
                db.get(AuthSession, session_id).revoked_at = utcnow()
            else:
                db.get(Project, project["id"]).deleted_at = utcnow()
        try:
            await anext(iterator)
            raise AssertionError("stream must end after authorization changes")
        except StopAsyncIteration:
            pass

    asyncio.run(read())


def test_slow_event_query_does_not_block_event_loop(execution_project, monkeypatch):
    import asyncio
    import time

    from starlette.requests import Request

    import videotranslate.routes.events as events
    from videotranslate.security import require_identity

    client, _, project = execution_project
    app = client.app
    cookie = "; ".join(f"{k}={v}" for k, v in client.cookies.items()).encode()
    request = Request(
        {"type": "http", "method": "GET", "path": "/", "headers": [(b"cookie", cookie)], "app": app}
    )
    with app.state.session_factory() as db:
        identity = require_identity(request, db)
        response = events.stream_events(project["id"], request, 0, False, None, identity, db)
    original = events.event_page

    def delayed(*args, **kwargs):
        time.sleep(0.3)
        return original(*args, **kwargs)

    monkeypatch.setattr(events, "event_page", delayed)

    async def exercise():
        ticked = asyncio.Event()

        async def tick():
            await asyncio.sleep(0.05)
            ticked.set()

        timer = asyncio.create_task(tick())
        await asyncio.sleep(0)  # Begin the timer before the delayed read.
        first = await anext(response.body_iterator)
        assert first.startswith("id:")
        assert ticked.is_set(), "database query blocked unrelated event-loop work"
        await timer

    asyncio.run(exercise())

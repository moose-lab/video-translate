import json


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


def test_stream_rechecks_revocation_between_polls(execution_project, monkeypatch):
    import asyncio
    from datetime import timedelta

    from starlette.requests import Request

    from videotranslate.models.core import AuthSession, utcnow
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
            db.get(AuthSession, session_id).expires_at = utcnow() - timedelta(seconds=1)
        try:
            await anext(iterator)
            raise AssertionError("stream must end after expiry")
        except StopAsyncIteration:
            pass

    asyncio.run(read())

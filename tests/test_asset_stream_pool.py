"""Slow authorized media readers must not monopolize SQL connections."""

import asyncio

import pytest
from starlette.requests import Request
from test_upload import make_project, upload


@pytest.mark.parametrize("range_value", [None, b"bytes=0-15"])
def test_download_releases_sql_before_storage_open_and_slow_body(
    client_factory, register, tiny_mp4, monkeypatch, range_value
):
    from videotranslate.routes.assets import asset_content
    from videotranslate.security import require_identity

    client = client_factory()
    project, headers = make_project(client, register)
    asset = upload(client, project["id"], headers, tiny_mp4).json()["asset"]
    app = client.app
    cookie = "; ".join(f"{k}={v}" for k, v in client.cookies.items()).encode()
    request_headers = [(b"cookie", cookie)]
    if range_value:
        request_headers.append((b"range", range_value))
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": request_headers,
            "app": app,
        }
    )
    original_open = app.state.storage.open

    def slow_open(*args, **kwargs):
        assert app.state.engine.pool.checkedout() == 0, "Storage I/O must run outside SQL"
        return original_open(*args, **kwargs)

    monkeypatch.setattr(app.state.storage, "open", slow_open)
    with app.state.session_factory() as db:
        identity = require_identity(request, db)
        response = asset_content(asset["id"], request, identity, db)
        assert app.state.engine.pool.checkedout() == 0, "Unconsumed video must release SQL"
        assert response.status_code == (206 if range_value else 200)
        assert response.headers["content-type"] == "video/mp4"

        async def read():
            return b"".join([chunk async for chunk in response.body_iterator])

        data = asyncio.run(read())
        assert data == (tiny_mp4[:16] if range_value else tiny_mp4)
        assert app.state.engine.pool.checkedout() == 0

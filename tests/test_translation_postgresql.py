"""Actual PostgreSQL runtime transactions; all remote responses remain recorded doubles."""

import os
from uuid import uuid4

import pytest
from dubbing_helpers import create_line, make_probed_project, make_track, selected
from test_translation_operations import drain, install_chat, request_body, view


@pytest.mark.parametrize("mode,count", [("Fast", 1), ("Cinematic", 4), ("Autofit", 5)])
def test_translation_modes_run_on_isolated_real_postgresql(
    client_factory, register, tmp_path, monkeypatch, mode, count
):
    import psycopg
    from psycopg import sql

    admin_url = os.environ.get("VT_TEST_POSTGRES_ADMIN_URL")
    if not admin_url:
        pytest.skip("Opt-in isolated PostgreSQL unavailable")
    name = "translation_runtime_" + uuid4().hex
    admin = psycopg.connect(admin_url, autocommit=True)
    admin.execute(sql.SQL("CREATE DATABASE {} OWNER vt_test").format(sql.Identifier(name)))
    url = (admin_url.rsplit("/", 1)[0] + "/" + name).replace(
        "postgresql://", "postgresql+psycopg://"
    )
    client = None
    try:
        fixture = make_probed_project(
            lambda: client_factory(database_url=url, provider_allowed_hosts="translator.example"),
            register,
            tmp_path,
        )
        client, headers, project = fixture
        selection = selected(fixture)
        line = create_line(fixture, selection, "IBM source", end_ms=300)["segment"]
        base = f"/api/projects/{project['id']}"
        track = make_track(client, headers, base, "ja", mode=mode)
        configured = client.put(
            "/api/providers/translation",
            headers=headers,
            json={
                "revision": 0,
                "adapter": "openai_compatible",
                "endpoint": "https://translator.example/v1",
                "model": "test-model",
                "credential_ref": None,
            },
        )
        assert configured.status_code == 200
        chat = install_chat(monkeypatch)
        path = base + "/language-tracks/ja/translate"
        queued = client.post(path, headers=headers, json=request_body(selection, line, track))
        assert queued.status_code == 202, queued.text
        drain(client)
        state = client.get(path + "/" + queued.json()["id"]).json()
        assert state["status"] == "review" and len(chat.calls) == count
        assert view(client, project, line, "ja")["approved"] is False
        body = request_body(selection, line, track)
        body["segments"][0]["revision"] = view(client, project, line, "ja")["revision"]
        assert client.post(path, headers=headers, json=body).status_code == 202
        drain(client)
        assert len(chat.calls) == count
    finally:
        if client:
            client.close()
            client.app.state.engine.dispose()
        admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))
        admin.close()

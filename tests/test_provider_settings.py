from sqlalchemy import select


def test_credential_encryption_cas_keep_clear_and_workspace_binding(client_factory, register):
    from videotranslate.models.providers import WorkspaceCredential
    from videotranslate.providers.vault import decrypt_credential

    client = client_factory()
    identity = register(client)
    headers = {"X-CSRF-Token": identity["csrf_token"]}
    token = "hf_fake_secret_for_testing"
    url = "/api/credentials/huggingface"
    assert client.put(url, json={"revision": 0, "token": token}).status_code == 403
    response = client.put(url, headers=headers, json={"revision": 0, "token": token})
    assert response.status_code == 200
    assert token not in response.text
    assert response.json()["configured"] is True
    with client.app.state.session_factory() as db:
        row = db.scalar(select(WorkspaceCredential))
        assert token not in row.ciphertext
        assert (
            decrypt_credential(
                client.app.state.settings, identity["workspace"]["id"], row.ciphertext
            )
            == token
        )
        import pytest

        with pytest.raises(ValueError):
            decrypt_credential(client.app.state.settings, "other-workspace", row.ciphertext)
    assert client.put(url, headers=headers, json={"revision": 0, "clear": True}).status_code == 409
    assert client.put(url, headers=headers, json={"revision": 1}).json()["configured"] is True
    assert client.put(url, headers=headers, json={"revision": 2, "token": ""}).status_code == 422
    assert (
        client.put(
            url, headers=headers, json={"revision": 2, "token": token, "clear": True}
        ).status_code
        == 422
    )
    assert (
        client.put(url, headers=headers, json={"revision": 2, "clear": True}).json()["configured"]
        is False
    )


def test_provider_revisions_are_immutable_and_tenant_scoped(client_factory, register):
    from videotranslate.providers.settings import resolve_revision

    client = client_factory()
    identity = register(client)
    headers = {"X-CSRF-Token": identity["csrf_token"]}
    url = "/api/providers/translation"
    first = {
        "revision": 0,
        "adapter": "hf_router",
        "endpoint": "https://router.huggingface.co/v1",
        "model": "one",
        "controls": {},
        "credential_ref": "huggingface",
    }
    response = client.put(url, json=first, headers=headers)
    assert response.status_code == 200, response.text
    second = {**first, "revision": 1, "model": "two"}
    assert client.put(url, json=second, headers=headers).status_code == 200
    assert client.put(url, json=second, headers=headers).status_code == 409
    with client.app.state.session_factory() as db:
        assert resolve_revision(db, identity["workspace"]["id"], "translation", 1)["model"] == "one"
        assert resolve_revision(db, identity["workspace"]["id"], "translation", 2)["model"] == "two"
        import pytest

        with pytest.raises(LookupError):
            resolve_revision(db, "foreign", "translation", 1)
    settings = client.get("/api/provider-settings").json()
    assert settings["providers"]["translation"]["revision"] == 2


def test_provider_rejects_untrusted_configuration_and_cross_slot_adapter(client_factory, register):
    client = client_factory()
    identity = register(client)
    headers = {"X-CSRF-Token": identity["csrf_token"]}
    base = {
        "revision": 0,
        "adapter": "hf_router",
        "endpoint": "https://router.huggingface.co/v1",
        "model": "one",
        "controls": {},
        "credential_ref": "huggingface",
    }
    for changes in (
        {"endpoint": "http://localhost/"},
        {"endpoint": "https://evil.example/"},
        {"endpoint": "https://u:p@router.huggingface.co/v1"},
        {"controls": {"token": "secret"}},
        {"credential_ref": "translation"},
    ):
        assert (
            client.put(
                "/api/providers/translation", headers=headers, json={**base, **changes}
            ).status_code
            == 422
        )
    assert client.put("/api/providers/separation", headers=headers, json=base).status_code == 422


def test_provider_migration_upgrade_and_downgrade(tmp_path):
    import os
    import subprocess

    from sqlalchemy import create_engine, inspect

    path = tmp_path / "migration.db"
    env = {**os.environ, "VT_DATABASE_URL": f"sqlite:///{path}", "VT_STORAGE_BACKEND": "local"}
    subprocess.run(
        [".venv/bin/alembic", "upgrade", "head"], env=env, check=True, capture_output=True
    )
    engine = create_engine(f"sqlite:///{path}")
    assert {
        "workspace_credentials",
        "provider_connections",
        "provider_connection_revisions",
    } <= set(inspect(engine).get_table_names())
    subprocess.run(
        [".venv/bin/alembic", "downgrade", "0002_durable_execution"],
        env=env,
        check=True,
        capture_output=True,
    )
    assert "workspace_credentials" not in inspect(engine).get_table_names()
    engine.dispose()


def test_new_project_initializes_existing_provider_fingerprint(client_factory, register):
    from videotranslate.execution.inputs import capture_inputs, initialize_inputs
    from videotranslate.models.core import Project

    client = client_factory()
    identity = register(client)
    headers = {"X-CSRF-Token": identity["csrf_token"]}
    body = {
        "revision": 0,
        "adapter": "hf_router",
        "endpoint": "https://router.huggingface.co/v1",
        "model": "one",
        "controls": {},
        "credential_ref": "huggingface",
    }
    assert client.put("/api/providers/translation", json=body, headers=headers).status_code == 200
    project = client.post("/api/projects", json={"name": "Film"}, headers=headers).json()
    with client.app.state.session_factory.begin() as db:
        row = db.get(Project, project["id"])
        initialize_inputs(db, row)
        assert capture_inputs(db, row, ["provider.translation"])

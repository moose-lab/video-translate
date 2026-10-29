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


def test_missing_required_credential_check_is_explicit_and_not_inference(client_factory, register):
    client = client_factory()
    identity = register(client)
    headers = {"X-CSRF-Token": identity["csrf_token"]}
    body = {
        "revision": 0,
        "adapter": "hf_router",
        "endpoint": "https://router.huggingface.co/v1",
        "model": "test/model",
        "controls": {},
        "credential_ref": "huggingface",
    }
    assert client.put("/api/providers/translation", json=body, headers=headers).status_code == 200
    response = client.post(
        "/api/providers/translation/check", json={"revision": 1}, headers=headers
    )
    assert response.status_code == 200
    assert response.json()["state"] == "credential_required"
    assert response.json()["inference_verified"] is False
    assert response.json()["credentials_valid"] is None


def test_old_check_cannot_overwrite_after_credential_rotation(
    client_factory, register, monkeypatch
):
    from videotranslate.providers.network import SafeHTTP

    client = client_factory()
    identity = register(client)
    headers = {"X-CSRF-Token": identity["csrf_token"]}
    assert (
        client.put(
            "/api/credentials/huggingface",
            headers=headers,
            json={"revision": 0, "token": "fake-first"},
        ).status_code
        == 200
    )
    body = {
        "revision": 0,
        "adapter": "hf_router",
        "endpoint": "https://router.huggingface.co/v1",
        "model": "test/model",
        "controls": {},
        "credential_ref": "huggingface",
    }
    assert client.put("/api/providers/translation", headers=headers, json=body).status_code == 200
    calls = 0

    def check(self, url, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            assert (
                client.put(
                    "/api/credentials/huggingface",
                    headers=headers,
                    json={"revision": 1, "token": "fake-second"},
                ).status_code
                == 200
            )
        return b"{}"

    monkeypatch.setattr(SafeHTTP, "get", check)
    response = client.post(
        "/api/providers/translation/check", headers=headers, json={"revision": 1}
    )
    assert response.status_code == 409
    assert (
        client.get("/api/provider-settings").json()["providers"]["translation"]["check_state"]
        is None
    )


def test_rejects_unsupported_or_out_of_range_omnivoice_controls(client_factory, register):
    client = client_factory()
    identity = register(client)
    headers = {"X-CSRF-Token": identity["csrf_token"]}
    body = {
        "revision": 0,
        "adapter": "omnivoice",
        "endpoint": "https://k2-fsa-omnivoice.hf.space",
        "space_id": "k2-fsa/OmniVoice",
        "model": "OmniVoice",
        "credential_ref": None,
        "controls": {},
    }
    for controls in ({"seed": 42}, {"ns": 1}, {"sp": 4}, {"dn": 1}, {"pot": True}):
        assert (
            client.put(
                "/api/providers/synthesis", headers=headers, json={**body, "controls": controls}
            ).status_code
            == 422
        )
    assert (
        client.put(
            "/api/providers/synthesis",
            headers=headers,
            json={**body, "controls": {"ns": 32, "sp": 1.0, "po": True}},
        ).status_code
        == 200
    )


def test_space_check_resolves_official_host_and_never_sends_hf_key_to_space(
    client_factory, register, monkeypatch
):
    from videotranslate.providers.network import SafeHTTP

    client = client_factory()
    identity = register(client)
    headers = {"X-CSRF-Token": identity["csrf_token"]}
    client.put(
        "/api/credentials/huggingface", headers=headers, json={"revision": 0, "token": "hf_fake"}
    )
    body = {
        "revision": 0,
        "adapter": "omnivoice",
        "endpoint": "https://k2-fsa-omnivoice.hf.space",
        "space_id": "k2-fsa/OmniVoice",
        "model": "OmniVoice",
        "credential_ref": "huggingface",
        "controls": {},
    }
    assert client.put("/api/providers/synthesis", headers=headers, json=body).status_code == 200
    seen = []

    def get(self, url, **kwargs):
        seen.append((url, kwargs.get("headers", {})))
        if url.endswith("/api/spaces/k2-fsa/OmniVoice"):
            return b'{"host":"https://k2-fsa-omnivoice.hf.space"}'
        if url.endswith("/gradio_api/info"):
            import json

            names = [
                "text",
                "lang",
                "ref_aud",
                "ref_text",
                "instruct",
                "ns",
                "gs",
                "dn",
                "sp",
                "du",
                "pp",
                "po",
            ]
            return json.dumps(
                {
                    "named_endpoints": {
                        "/_clone_fn": {
                            "parameters": [
                                {
                                    "parameter_name": n,
                                    **({"type": {"enum": ["Japanese"]}} if n == "lang" else {}),
                                }
                                for n in names
                            ],
                            "returns": [{"component": "Audio"}, {"component": "Textbox"}],
                        }
                    }
                }
            ).encode()
        return b"{}"

    monkeypatch.setattr(SafeHTTP, "get", get)
    response = client.post("/api/providers/synthesis/check", headers=headers, json={"revision": 1})
    assert response.status_code == 200
    assert response.json()["reachable"] is True and response.json()["credentials_valid"] is True
    assert all(
        "Authorization" not in headers
        for url, headers in seen
        if url != "https://huggingface.co/api/whoami-v2"
    )
    assert any(url == "https://k2-fsa-omnivoice.hf.space/gradio_api/info" for url, _ in seen)


def test_nvidia_check_reads_real_health_and_config_shape(client_factory, register, monkeypatch):
    from videotranslate.providers.network import SafeHTTP

    client = client_factory()
    identity = register(client)
    headers = {"X-CSRF-Token": identity["csrf_token"]}
    body = {
        "revision": 0,
        "adapter": "nvidia_stream",
        "endpoint": "https://nvidia-nemotron-diarization.hf.space",
        "space_id": "nvidia/nemotron-diarization",
        "model": "nemotron-diarization",
        "credential_ref": None,
        "controls": {},
    }
    assert client.put("/api/providers/transcription", headers=headers, json=body).status_code == 200

    def get(self, url, **kwargs):
        if "/api/spaces/" in url:
            return b'{"host":"https://nvidia-nemotron-diarization.hf.space"}'
        if url.endswith("/health"):
            return b'{"ok":true}'
        if url.endswith("/api/config"):
            return b'{"ready":true}'
        raise AssertionError(url)

    monkeypatch.setattr(SafeHTTP, "get", get)
    result = client.post(
        "/api/providers/transcription/check", headers=headers, json={"revision": 1}
    ).json()
    assert result["reachable"] is True
    assert result["limits"]["max_duration_seconds"] == 120
    assert result["inference_verified"] is False


def test_hf_model_check_reads_model_metadata_and_account_separately(
    client_factory, register, monkeypatch
):
    from videotranslate.providers.network import SafeHTTP

    client = client_factory()
    identity = register(client)
    headers = {"X-CSRF-Token": identity["csrf_token"]}
    client.put(
        "/api/credentials/huggingface", headers=headers, json={"revision": 0, "token": "hf_fake"}
    )
    body = {
        "revision": 0,
        "adapter": "hf_router",
        "endpoint": "https://router.huggingface.co/v1",
        "model": "openai/whisper-large-v3",
        "credential_ref": "huggingface",
        "controls": {},
    }
    assert client.put("/api/providers/verification", headers=headers, json=body).status_code == 200
    seen = []

    def get(self, url, **kwargs):
        seen.append((url, kwargs.get("headers", {})))
        return b'{"id":"openai/whisper-large-v3"}' if "/api/models/" in url else b"{}"

    monkeypatch.setattr(SafeHTTP, "get", get)
    result = client.post(
        "/api/providers/verification/check", headers=headers, json={"revision": 1}
    ).json()
    assert result["reachable"] is True
    assert seen[0][0] == "https://huggingface.co/api/models/openai/whisper-large-v3"
    assert seen[0][1] == {}
    assert seen[1][0] == "https://huggingface.co/api/whoami-v2"
    assert result["inference_verified"] is False


def test_check_reports_quota_without_provider_body(client_factory, register, monkeypatch):
    from videotranslate.providers.contracts import ProviderError
    from videotranslate.providers.network import SafeHTTP

    client = client_factory()
    identity = register(client)
    headers = {"X-CSRF-Token": identity["csrf_token"]}
    client.put(
        "/api/credentials/huggingface", headers=headers, json={"revision": 0, "token": "hf_fake"}
    )
    body = {
        "revision": 0,
        "adapter": "hf_router",
        "endpoint": "https://router.huggingface.co/v1",
        "model": "openai/whisper-large-v3",
        "credential_ref": "huggingface",
        "controls": {},
    }
    assert client.put("/api/providers/verification", headers=headers, json=body).status_code == 200

    def get(self, *args, **kwargs):
        raise ProviderError("quota")

    monkeypatch.setattr(SafeHTTP, "get", get)
    response = client.post(
        "/api/providers/verification/check", headers=headers, json={"revision": 1}
    )
    assert response.json()["state"] == "quota"
    assert "hf_fake" not in response.text


def test_invalid_hf_account_check_sets_credential_validity_false(
    client_factory, register, monkeypatch
):
    from videotranslate.providers.contracts import ProviderError
    from videotranslate.providers.network import SafeHTTP

    client = client_factory()
    identity = register(client)
    headers = {"X-CSRF-Token": identity["csrf_token"]}
    client.put(
        "/api/credentials/huggingface", headers=headers, json={"revision": 0, "token": "hf_fake"}
    )
    body = {
        "revision": 0,
        "adapter": "hf_router",
        "endpoint": "https://router.huggingface.co/v1",
        "model": "openai/whisper-large-v3",
        "credential_ref": "huggingface",
        "controls": {},
    }
    client.put("/api/providers/verification", headers=headers, json=body)

    def get(self, url, **kwargs):
        if url.endswith("/whoami-v2"):
            raise ProviderError("auth")
        return b'{"id":"openai/whisper-large-v3"}'

    monkeypatch.setattr(SafeHTTP, "get", get)
    result = client.post(
        "/api/providers/verification/check", headers=headers, json={"revision": 1}
    ).json()
    assert result["credentials_valid"] is False
    assert result["state"] == "auth"


def test_space_check_does_not_accept_incompatible_gradio_schema(
    client_factory, register, monkeypatch
):
    from videotranslate.providers.network import SafeHTTP

    client = client_factory()
    identity = register(client)
    headers = {"X-CSRF-Token": identity["csrf_token"]}
    body = {
        "revision": 0,
        "adapter": "demucs",
        "endpoint": "https://kajise-demucs-v4-ft-2s.hf.space",
        "space_id": "kajise/Demucs_v4-FT_2s",
        "model": "htdemucs_ft",
        "credential_ref": None,
        "controls": {},
    }
    client.put("/api/providers/separation", headers=headers, json=body)

    def get(self, url, **kwargs):
        if "/api/spaces/" in url:
            return b'{"host":"https://kajise-demucs-v4-ft-2s.hf.space"}'
        return b'{"named_endpoints":{"/predict":{"parameters":[],"returns":[]}}}'

    monkeypatch.setattr(SafeHTTP, "get", get)
    result = client.post(
        "/api/providers/separation/check", headers=headers, json={"revision": 1}
    ).json()
    assert result["state"] == "check_failed"
    assert result["inference_verified"] is False


def test_hf_model_check_rejects_malformed_metadata(client_factory, register, monkeypatch):
    from videotranslate.providers.network import SafeHTTP

    client = client_factory()
    identity = register(client)
    headers = {"X-CSRF-Token": identity["csrf_token"]}
    client.put(
        "/api/credentials/huggingface", headers=headers, json={"revision": 0, "token": "hf_fake"}
    )
    body = {
        "revision": 0,
        "adapter": "hf_router",
        "endpoint": "https://router.huggingface.co/v1",
        "model": "openai/whisper-large-v3",
        "credential_ref": "huggingface",
        "controls": {},
    }
    client.put("/api/providers/verification", headers=headers, json=body)
    monkeypatch.setattr(SafeHTTP, "get", lambda *args, **kwargs: b"{}")
    result = client.post(
        "/api/providers/verification/check", headers=headers, json={"revision": 1}
    ).json()
    assert result["state"] == "check_failed"
    assert result["inference_verified"] is False


def test_hf_router_configuration_cannot_target_arbitrary_hf_space(client_factory, register):
    client = client_factory()
    identity = register(client)
    headers = {"X-CSRF-Token": identity["csrf_token"]}
    body = {
        "revision": 0,
        "adapter": "hf_router",
        "endpoint": "https://unrelated.hf.space/v1",
        "model": "test/model",
        "credential_ref": "huggingface",
        "controls": {},
    }
    assert client.put("/api/providers/translation", headers=headers, json=body).status_code == 422


def test_credential_rotation_makes_prior_account_validation_stale_without_erasing_health(
    client_factory, register, monkeypatch
):
    from videotranslate.providers.network import SafeHTTP

    client = client_factory()
    identity = register(client)
    headers = {"X-CSRF-Token": identity["csrf_token"]}
    client.put(
        "/api/credentials/huggingface", headers=headers, json={"revision": 0, "token": "hf_fake1"}
    )
    body = {
        "revision": 0,
        "adapter": "hf_router",
        "endpoint": "https://router.huggingface.co/v1",
        "model": "openai/whisper-large-v3",
        "credential_ref": "huggingface",
        "controls": {},
    }
    client.put("/api/providers/verification", headers=headers, json=body)

    def get(self, url, **kwargs):
        return b'{"id":"openai/whisper-large-v3"}' if "/api/models/" in url else b"{}"

    monkeypatch.setattr(SafeHTTP, "get", get)
    assert (
        client.post(
            "/api/providers/verification/check", headers=headers, json={"revision": 1}
        ).json()["credentials_valid"]
        is True
    )
    assert (
        client.put(
            "/api/credentials/huggingface",
            headers=headers,
            json={"revision": 1, "token": "hf_fake2"},
        ).status_code
        == 200
    )
    state = client.get("/api/provider-settings").json()["providers"]["verification"]["check_state"]
    assert state["reachable"] is True
    assert state["credentials_valid"] is None


def test_missing_model_is_configuration_required_without_inference(client_factory, register):
    client = client_factory()
    identity = register(client)
    headers = {"X-CSRF-Token": identity["csrf_token"]}
    client.put(
        "/api/credentials/huggingface", headers=headers, json={"revision": 0, "token": "hf_fake"}
    )
    body = {
        "revision": 0,
        "adapter": "hf_router",
        "endpoint": "https://router.huggingface.co/v1",
        "model": "",
        "credential_ref": "huggingface",
        "controls": {},
    }
    client.put("/api/providers/translation", headers=headers, json=body)
    result = client.post(
        "/api/providers/translation/check", headers=headers, json={"revision": 1}
    ).json()
    assert result["state"] == "configuration_required"
    assert result["inference_verified"] is False


def test_omnivoice_without_key_is_explicit_public_demo(client_factory, register, monkeypatch):
    import json

    from videotranslate.providers.network import SafeHTTP

    client = client_factory()
    identity = register(client)
    headers = {"X-CSRF-Token": identity["csrf_token"]}
    body = {
        "revision": 0,
        "adapter": "omnivoice",
        "endpoint": "https://k2-fsa-omnivoice.hf.space",
        "space_id": "k2-fsa/OmniVoice",
        "model": "OmniVoice",
        "credential_ref": "huggingface",
        "controls": {},
    }
    client.put("/api/providers/synthesis", headers=headers, json=body)

    def get(self, url, **kwargs):
        if "/api/spaces/" in url:
            return b'{"host":"https://k2-fsa-omnivoice.hf.space"}'
        names = [
            "text",
            "lang",
            "ref_aud",
            "ref_text",
            "instruct",
            "ns",
            "gs",
            "dn",
            "sp",
            "du",
            "pp",
            "po",
        ]
        return json.dumps(
            {
                "named_endpoints": {
                    "/_clone_fn": {
                        "parameters": [
                            {
                                "parameter_name": n,
                                **({"type": {"enum": ["Japanese"]}} if n == "lang" else {}),
                            }
                            for n in names
                        ],
                        "returns": [{"component": "Audio"}, {"component": "Textbox"}],
                    }
                }
            }
        ).encode()

    monkeypatch.setattr(SafeHTTP, "get", get)
    result = client.post(
        "/api/providers/synthesis/check", headers=headers, json={"revision": 1}
    ).json()
    assert result["credential_mode"] == "public_demo"
    assert result["credentials_valid"] is None and result["inference_verified"] is False


def test_omnivoice_metadata_distinguishes_code_and_model_license(
    client_factory, register, monkeypatch
):
    import json

    from videotranslate.providers.network import SafeHTTP

    client = client_factory()
    identity = register(client)
    headers = {"X-CSRF-Token": identity["csrf_token"]}
    body = {
        "revision": 0,
        "adapter": "omnivoice",
        "endpoint": "https://k2-fsa-omnivoice.hf.space",
        "space_id": "k2-fsa/OmniVoice",
        "model": "OmniVoice",
        "credential_ref": None,
        "controls": {},
    }
    client.put("/api/providers/synthesis", headers=headers, json=body)

    def get(self, url, **kwargs):
        if "/api/spaces/" in url:
            return b'{"host":"https://k2-fsa-omnivoice.hf.space"}'
        names = [
            "text",
            "lang",
            "ref_aud",
            "ref_text",
            "instruct",
            "ns",
            "gs",
            "dn",
            "sp",
            "du",
            "pp",
            "po",
        ]
        return json.dumps(
            {
                "named_endpoints": {
                    "/_clone_fn": {
                        "parameters": [
                            {
                                "parameter_name": n,
                                **({"type": {"enum": ["Japanese"]}} if n == "lang" else {}),
                            }
                            for n in names
                        ],
                        "returns": [{"component": "Audio"}, {"component": "Textbox"}],
                    }
                }
            }
        ).encode()

    monkeypatch.setattr(SafeHTTP, "get", get)
    result = client.post(
        "/api/providers/synthesis/check", headers=headers, json={"revision": 1}
    ).json()
    assert result["capabilities"]["model_license"] == "CC-BY-NC"
    assert result["capabilities"]["upstream_code_license"] == "Apache-2.0"
    assert result["inference_verified"] is False


def test_check_uses_admin_proxy_settings_without_exposing_them(
    client_factory, register, monkeypatch
):
    from videotranslate.providers.network import SafeHTTP

    proxy = "http://user:fake-proxy-secret@127.0.0.1:7897"
    client = client_factory(provider_proxy_url=proxy, provider_dns_over_https=True)
    identity = register(client)
    headers = {"X-CSRF-Token": identity["csrf_token"]}
    body = {
        "revision": 0,
        "adapter": "nvidia_stream",
        "endpoint": "https://nvidia-nemotron-diarization.hf.space",
        "space_id": "nvidia/nemotron-diarization",
        "model": "nemotron-diarization",
        "credential_ref": None,
        "controls": {},
    }
    client.put("/api/providers/transcription", headers=headers, json=body)
    seen = []
    original = SafeHTTP.__init__

    def init(self, **kwargs):
        seen.append(kwargs)
        original(
            self,
            transport=__import__("httpx").MockTransport(
                lambda request: __import__("httpx").Response(500)
            ),
            **kwargs,
        )

    def get(self, url, **kwargs):
        if "/api/spaces/" in url:
            return b'{"host":"https://nvidia-nemotron-diarization.hf.space"}'
        return b'{"ok":true}' if url.endswith("/health") else b'{"ready":true}'

    monkeypatch.setattr(SafeHTTP, "__init__", init)
    monkeypatch.setattr(SafeHTTP, "get", get)
    response = client.post(
        "/api/providers/transcription/check", headers=headers, json={"revision": 1}
    )
    assert response.json()["reachable"] is True
    assert seen[0]["proxy_url"] == proxy and seen[0]["use_doh"] is True
    assert (
        "fake-proxy-secret" not in response.text
        and "fake-proxy-secret" not in client.get("/api/provider-settings").text
    )


def test_non_owner_cannot_mutate_credentials_or_provider(client_factory, register):
    from sqlalchemy import update

    from videotranslate.models.core import Membership

    client = client_factory()
    identity = register(client)
    headers = {"X-CSRF-Token": identity["csrf_token"]}
    with client.app.state.session_factory.begin() as db:
        db.execute(
            update(Membership)
            .where(Membership.workspace_id == identity["workspace"]["id"])
            .values(role="member")
        )
    assert (
        client.put(
            "/api/credentials/huggingface",
            headers=headers,
            json={"revision": 0, "token": "hf_fake"},
        ).status_code
        == 403
    )
    body = {
        "revision": 0,
        "adapter": "demucs",
        "endpoint": "https://kajise-demucs-v4-ft-2s.hf.space",
        "space_id": "kajise/Demucs_v4-FT_2s",
        "model": "htdemucs_ft",
        "controls": {},
        "credential_ref": None,
    }
    assert client.put("/api/providers/separation", headers=headers, json=body).status_code == 403


def test_setting_change_invalidates_only_dependent_runs_credential_rotation_does_not(
    execution_project,
):
    from sqlalchemy import select

    from videotranslate.execution.inputs import capture_inputs, set_inputs
    from videotranslate.models.core import Project
    from videotranslate.models.execution import StageRun

    client, headers, project = execution_project
    body = {
        "revision": 0,
        "adapter": "hf_router",
        "endpoint": "https://router.huggingface.co/v1",
        "model": "one/model",
        "controls": {},
        "credential_ref": "huggingface",
    }
    assert client.put("/api/providers/translation", headers=headers, json=body).status_code == 200
    sf = client.app.state.session_factory
    with sf.begin() as db:
        p = db.get(Project, project["id"])
        set_inputs(db, p, {"other.input": "unchanged"})
        for key, stage in [("provider.translation", "translate"), ("other.input", "other")]:
            db.add(
                StageRun(
                    workspace_id=p.workspace_id,
                    project_id=p.id,
                    stage=stage,
                    scope_key=stage,
                    options={},
                    input_project_revision=p.revision,
                    dependency_snapshot=capture_inputs(db, p, [key]),
                    dependency_fingerprint="a" * 64,
                    request_fingerprint="b" * 64,
                    output_key="output." + stage,
                    status="succeeded",
                )
            )
    assert (
        client.put(
            "/api/credentials/huggingface",
            headers=headers,
            json={"revision": 0, "token": "hf_fake"},
        ).status_code
        == 200
    )
    with sf() as db:
        assert all(not run.is_stale for run in db.scalars(select(StageRun)).all())
    assert (
        client.put(
            "/api/providers/translation",
            headers=headers,
            json={**body, "revision": 1, "model": "two/model"},
        ).status_code
        == 200
    )
    with sf() as db:
        runs = {r.stage: r for r in db.scalars(select(StageRun)).all()}
        assert runs["translate"].is_stale is True
        assert runs["other"].is_stale is False


def test_old_connection_check_cannot_overwrite_new_revision(client_factory, register, monkeypatch):
    from videotranslate.providers.network import SafeHTTP

    client = client_factory()
    identity = register(client)
    headers = {"X-CSRF-Token": identity["csrf_token"]}
    body = {
        "revision": 0,
        "adapter": "nvidia_stream",
        "endpoint": "https://nvidia-nemotron-diarization.hf.space",
        "space_id": "nvidia/nemotron-diarization",
        "model": "nemotron-diarization",
        "credential_ref": None,
        "controls": {},
    }
    assert client.put("/api/providers/transcription", headers=headers, json=body).status_code == 200
    calls = 0

    def get(self, url, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            assert (
                client.put(
                    "/api/providers/transcription",
                    headers=headers,
                    json={**body, "revision": 1, "controls": {"max_speakers": 4}},
                ).status_code
                == 200
            )
            return b'{"host":"https://nvidia-nemotron-diarization.hf.space"}'
        return b'{"ok":true}' if url.endswith("/health") else b'{"ready":true}'

    monkeypatch.setattr(SafeHTTP, "get", get)
    assert (
        client.post(
            "/api/providers/transcription/check", headers=headers, json={"revision": 1}
        ).status_code
        == 409
    )
    assert (
        client.get("/api/provider-settings").json()["providers"]["transcription"]["check_state"]
        is None
    )


def test_hf_provider_suffix_uses_repository_for_metadata(client_factory, register, monkeypatch):
    from videotranslate.providers.network import SafeHTTP

    client = client_factory()
    identity = register(client)
    headers = {"X-CSRF-Token": identity["csrf_token"]}
    client.put(
        "/api/credentials/huggingface", headers=headers, json={"revision": 0, "token": "hf_fake"}
    )
    body = {
        "revision": 0,
        "adapter": "hf_router",
        "endpoint": "https://router.huggingface.co/v1",
        "model": "Qwen/Qwen3-235B-A22B-Instruct-2507:deepinfra",
        "credential_ref": "huggingface",
        "controls": {},
    }
    client.put("/api/providers/translation", headers=headers, json=body)
    seen = []

    def get(self, url, **kwargs):
        seen.append(url)
        return b'{"id":"Qwen/Qwen3-235B-A22B-Instruct-2507"}' if "/api/models/" in url else b"{}"

    monkeypatch.setattr(SafeHTTP, "get", get)
    assert (
        client.post(
            "/api/providers/translation/check", headers=headers, json={"revision": 1}
        ).json()["reachable"]
        is True
    )
    assert seen[0] == "https://huggingface.co/api/models/Qwen/Qwen3-235B-A22B-Instruct-2507"
    assert (
        client.get("/api/provider-settings").json()["providers"]["translation"]["model"]
        == body["model"]
    )


def test_unimplemented_preset_models_and_nvidia_hosts_are_rejected(client_factory, register):
    client = client_factory()
    identity = register(client)
    headers = {"X-CSRF-Token": identity["csrf_token"]}
    cases = [
        (
            "transcription",
            {
                "adapter": "nvidia_stream",
                "endpoint": "https://other.hf.space",
                "space_id": "other/nvidia",
                "model": "wrong",
                "credential_ref": None,
            },
        ),
        (
            "synthesis",
            {
                "adapter": "omnivoice",
                "endpoint": "https://k2-fsa-omnivoice.hf.space",
                "space_id": "k2-fsa/OmniVoice",
                "model": "other",
                "credential_ref": None,
            },
        ),
        (
            "separation",
            {
                "adapter": "demucs",
                "endpoint": "https://kajise-demucs-v4-ft-2s.hf.space",
                "space_id": "kajise/Demucs_v4-FT_2s",
                "model": "other",
                "credential_ref": None,
            },
        ),
    ]
    for slot, body in cases:
        assert (
            client.put(
                "/api/providers/" + slot,
                headers=headers,
                json={"revision": 0, "controls": {}, **body},
            ).status_code
            == 422
        )


def test_capability_check_has_structured_declared_and_tested_coverage(
    client_factory, register, monkeypatch
):
    import json

    from videotranslate.providers.network import SafeHTTP

    client = client_factory()
    identity = register(client)
    headers = {"X-CSRF-Token": identity["csrf_token"]}
    body = {
        "revision": 0,
        "adapter": "omnivoice",
        "endpoint": "https://k2-fsa-omnivoice.hf.space",
        "space_id": "k2-fsa/OmniVoice",
        "model": "OmniVoice",
        "credential_ref": None,
        "controls": {},
    }
    assert client.put("/api/providers/synthesis", headers=headers, json=body).status_code == 200

    def get(self, url, **kwargs):
        if "/api/spaces/" in url:
            return b'{"host":"https://k2-fsa-omnivoice.hf.space"}'
        names = [
            "text",
            "lang",
            "ref_aud",
            "ref_text",
            "instruct",
            "ns",
            "gs",
            "dn",
            "sp",
            "du",
            "pp",
            "po",
        ]
        params = [{"parameter_name": n} for n in names]
        params[1]["type"] = {"enum": ["Japanese", "Chinese"]}
        return json.dumps(
            {
                "named_endpoints": {
                    "/_clone_fn": {
                        "parameters": params,
                        "returns": [{"component": "Audio"}, {"component": "Textbox"}],
                    }
                }
            }
        ).encode()

    monkeypatch.setattr(SafeHTTP, "get", get)
    data = client.post(
        "/api/providers/synthesis/check", headers=headers, json={"revision": 1}
    ).json()["capabilities"]
    assert data["stage"] == "synthesis" and data["language_support"] == "unknown"
    assert set(data["supported_languages"]) == {"ja", "zh"}
    assert data["tested_languages"] == [] and data["tested_coverage"] == "unknown"
    assert data["resumable"] is True and data["cancel_supported"] is False


def test_settings_exposes_machine_readable_unknown_capabilities_before_checks(
    client_factory, register
):
    client = client_factory()
    register(client)
    result = client.get("/api/provider-settings").json()["providers"]
    assert set(result) == {
        "separation",
        "transcription",
        "translation",
        "synthesis",
        "verification",
    }
    assert all(result[slot]["capabilities"]["stage"] == slot for slot in result)
    assert all(result[slot]["capabilities"]["tested_coverage"] == "unknown" for slot in result)


def test_legacy_unsupported_preset_reports_configuration_without_network(
    client_factory, register, monkeypatch
):
    from sqlalchemy import select

    from videotranslate.models.providers import ProviderConnection
    from videotranslate.providers.network import SafeHTTP

    client = client_factory()
    identity = register(client)
    headers = {"X-CSRF-Token": identity["csrf_token"]}
    body = {
        "revision": 0,
        "adapter": "nvidia_stream",
        "endpoint": "https://nvidia-nemotron-diarization.hf.space",
        "space_id": "nvidia/nemotron-diarization",
        "model": "nemotron-diarization",
        "credential_ref": None,
        "controls": {},
    }
    client.put("/api/providers/transcription", headers=headers, json=body)
    with client.app.state.session_factory.begin() as db:
        row = db.scalar(select(ProviderConnection))
        row.settings = {**row.settings, "model": "unsupported"}
    monkeypatch.setattr(
        SafeHTTP, "get", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("no network"))
    )
    result = client.post(
        "/api/providers/transcription/check", headers=headers, json={"revision": 1}
    ).json()
    assert result["state"] == "configuration_required"


def test_nvidia_capability_declares_english_only_and_no_resumption():
    from videotranslate.providers.settings import capability_contract

    data = capability_contract("transcription", "nvidia_stream")
    assert data["stage"] == "transcription"
    assert data["language_support"] == "unsupported"
    assert set(data["supported_languages"]) == {"en", "en-US", "en-GB"}
    assert data["tested_coverage"] == "unknown" and data["tested_languages"] == ()
    assert (
        data["max_duration_seconds"] == 120
        and not data["resumable"]
        and not data["cancel_supported"]
    )


def test_asr_verification_rejects_provider_suffix_and_legacy_check_is_configuration_required(
    client_factory, register, monkeypatch
):
    from sqlalchemy import select

    from videotranslate.models.providers import ProviderConnection
    from videotranslate.providers.network import SafeHTTP

    client = client_factory()
    identity = register(client)
    headers = {"X-CSRF-Token": identity["csrf_token"]}
    client.put(
        "/api/credentials/huggingface", headers=headers, json={"revision": 0, "token": "hf_fake"}
    )
    body = {
        "revision": 0,
        "adapter": "hf_router",
        "endpoint": "https://router.huggingface.co/v1",
        "model": "openai/whisper-large-v3",
        "credential_ref": "huggingface",
        "controls": {},
    }
    assert (
        client.put(
            "/api/providers/verification",
            headers=headers,
            json={**body, "model": "openai/whisper-large-v3:fastest"},
        ).status_code
        == 422
    )
    assert client.put("/api/providers/verification", headers=headers, json=body).status_code == 200
    with client.app.state.session_factory.begin() as db:
        row = db.scalar(select(ProviderConnection))
        row.settings = {**row.settings, "model": "openai/whisper-large-v3:fastest"}
    monkeypatch.setattr(
        SafeHTTP,
        "get",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not contact provider")),
    )
    response = client.post(
        "/api/providers/verification/check", headers=headers, json={"revision": 1}
    )
    assert response.status_code == 200
    assert response.json()["state"] == "configuration_required"
    assert response.json()["inference_verified"] is False


def test_hf_timestamped_asr_is_selectable_with_honest_pinned_capabilities(client_factory, register):
    client = client_factory()
    auth = register(client)
    headers = {"X-CSRF-Token": auth["csrf_token"]}
    config = {
        "revision": 0,
        "adapter": "hf_asr",
        "endpoint": "https://router.huggingface.co/v1",
        "model": "openai/whisper-large-v3",
        "credential_ref": "huggingface",
    }
    response = client.put("/api/providers/transcription", headers=headers, json=config)
    assert response.status_code == 200, response.text
    settings = client.get("/api/provider-settings").json()["providers"]["transcription"]
    caps = settings["capabilities"]
    assert len(caps["supported_languages"]) == 95
    assert {"en", "jv", "npi", "ja", "zh"} <= set(caps["supported_languages"])
    assert caps["auto_detection"] is True and caps["speaker_labels"] is False
    assert caps["inference_verified"] is False and caps["tested_languages"] == []
    assert caps["detected_language_guaranteed"] is False
    assert caps["task_route"] == "hf-inference/models/{model}"
    config["revision"], config["model"] = 1, "custom/asr"
    assert (
        client.put("/api/providers/transcription", headers=headers, json=config).status_code == 200
    )
    caps = client.get("/api/provider-settings").json()["providers"]["transcription"]["capabilities"]
    assert caps["language_support"] == "unknown" and caps["supported_languages"] == []
    assert caps["auto_detection"] is False
    config["revision"], config["model"] = 2, "custom/asr:provider"
    assert (
        client.put("/api/providers/transcription", headers=headers, json=config).status_code == 422
    )

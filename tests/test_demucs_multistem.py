"""Four-stem contract doubles and real CPU audio; no remote inference."""

import json

import pytest

PROFILE = {
    "revision": 0,
    "adapter": "demucs_multistem",
    "space_id": "teamup-tech/Demucs",
    "endpoint": "https://teamup-tech-demucs.hf.space",
    "model": "htdemucs",
    "credential_ref": None,
    "controls": {},
}
SHA = "541b5b5bdee7e1eb6163d6f4e064e9e24f33c40c"


def schema():
    return {
        "named_endpoints": {
            "/process": {
                "parameters": [
                    {
                        "parameter_name": "input_0",
                        "component": "Audio",
                        "python_type": {"type": "filepath"},
                        "type": {
                            "type": "object",
                            "title": "FileData",
                            "properties": {"path": {"type": "string"}},
                            "required": ["path"],
                        },
                    },
                    {
                        "parameter_name": "input_1",
                        "component": "Dropdown",
                        "type": {
                            "type": "string",
                            "enum": ["htdemucs", "mdx_extra", "mdx_extra_q"],
                        },
                    },
                ],
                "returns": [
                    {
                        "component": "Audio",
                        "label": label,
                        "python_type": {"type": "filepath"},
                        "type": {
                            "type": "object",
                            "title": "FileData",
                            "properties": {"path": {"type": "string"}},
                            "required": ["path"],
                        },
                    }
                    for label in ("Drums", "Bass", "Vocals", "Other")
                ],
            }
        }
    }


def test_explicit_profile_settings_and_capabilities(client_factory, register):
    client = client_factory()
    auth = register(client)
    headers = {"X-CSRF-Token": auth["csrf_token"]}
    url = "/api/providers/separation"
    for change in (
        {"model": "htdemucs_ft"},
        {"space_id": "other/Demucs"},
        {"endpoint": "https://other.hf.space"},
        {"credential_ref": "huggingface"},
        {"controls": {"model": "htdemucs"}},
    ):
        assert client.put(url, json=PROFILE | change, headers=headers).status_code == 422
    response = client.put(url, json=PROFILE, headers=headers)
    assert response.status_code == 200, response.text
    saved = client.get("/api/provider-settings").json()["providers"]["separation"]
    assert saved["capabilities"]["resumable"] is True
    assert saved["capabilities"]["inference_verified"] is False
    assert saved["capabilities"]["outputs"] == ["drums", "bass", "vocals", "other"]
    assert saved["capabilities"]["instrumental_sources"] == ["drums", "bass", "other"]
    assert saved["capabilities"]["api_name"] == "process"


def test_four_stem_schema_is_exact():
    from videotranslate.providers.gradio import validate_endpoint_schema

    validate_endpoint_schema(schema(), "demucs_multistem")
    bad = []
    for field, value in (
        ("component", "File"),
        ("type", {"type": "string"}),
        ("label", "Instrumental"),
    ):
        info = schema()
        info["named_endpoints"]["/process"]["returns"][3][field] = value
        bad.append(info)
    info = schema()
    info["named_endpoints"]["/process"]["returns"].reverse()
    bad.append(info)
    info = schema()
    info["named_endpoints"]["/process"]["parameters"].reverse()
    bad.append(info)
    info = schema()
    info["named_endpoints"]["/process"]["parameters"][1]["type"]["enum"] = ["htdemucs_ft"]
    bad.append(info)
    info = schema()
    info["named_endpoints"]["/process"]["parameters"][0]["component"] = "File"
    bad.append(info)
    for info in bad:
        with pytest.raises(ValueError, match="Incompatible"):
            validate_endpoint_schema(info, "demucs_multistem")
    with pytest.raises(ValueError):
        validate_endpoint_schema(schema(), "demucs")


class ProtocolDouble:
    allowed_hosts = set()

    def __init__(self, info=None, sha=SHA):
        self.info = info or schema()
        self.sha = sha
        self.calls = []

    def get(self, url, **kw):
        assert not kw.get("headers")
        if "/api/spaces/" in url:
            return json.dumps({"host": PROFILE["endpoint"], "sha": self.sha}).encode()
        return json.dumps(self.info).encode()

    def upload(self, url, **kw):
        self.calls.append(("upload", url))
        assert kw.get("headers") == {}
        return ["/tmp/upload.wav"]

    def post_json(self, url, body, **kw):
        assert kw.get("headers") == {}
        self.calls.append(("post", url, body))
        return b'{"event_id":"real-shaped-test-id"}'


def test_four_stem_prepare_submit_and_invalid_config_precedes_named_post():
    from videotranslate.providers.demucs import prepare_separation, submit_prepared

    http = ProtocolDouble()
    prepared = prepare_separation(
        http,
        audio=b"fixture",
        adapter="demucs_multistem",
        model="htdemucs",
        space_id=PROFILE["space_id"],
    )
    assert [c[0] for c in http.calls] == ["upload"]
    assert prepared.api_name == "process"
    assert prepared.output_mapping == ("drums", "bass", "vocals", "other")
    assert submit_prepared(http, prepared) == "real-shaped-test-id"
    assert http.calls[-1] == (
        "post",
        PROFILE["endpoint"] + "/gradio_api/call/process",
        {"data": [prepared.reference, "htdemucs"]},
    )
    bad = schema()
    bad["named_endpoints"]["/process"]["returns"].reverse()
    for broken in (ProtocolDouble(bad), ProtocolDouble(sha="changed")):
        with pytest.raises(ValueError):
            prepare_separation(
                broken,
                audio=b"fixture",
                adapter="demucs_multistem",
                model="htdemucs",
                space_id=PROFILE["space_id"],
            )
        assert not broken.calls


def test_four_distinct_actual_filedata_paths_and_legacy_default():
    from videotranslate.providers.demucs import normalize_stems

    files = [
        {"path": f"/tmp/{stem}.wav", "meta": {"_type": "gradio.FileData"}}
        for stem in ("drums", "bass", "vocals", "other")
    ]
    assert list(normalize_stems(files, "demucs_multistem")) == ["drums", "bass", "vocals", "other"]
    for broken in (
        files[:-1],
        files + files[:1],
        files[:3] + [files[0]],
        files[:3] + [None],
        files[:3] + [{"path": "https://host/file"}],
        files[:3] + [{"path": "/tmp/\nbad"}],
    ):
        with pytest.raises(ValueError):
            normalize_stems(broken, "demucs_multistem")
    assert list(normalize_stems(files[:2])) == ["vocals", "instrumental"]
    with pytest.raises(ValueError):
        normalize_stems(files)


def configured_run(fixture):
    from dubbing_helpers import selected

    from videotranslate.execution.worker import Worker

    client, headers, project = fixture
    selected(fixture)
    assert client.put("/api/providers/separation", json=PROFILE, headers=headers).status_code == 200
    base = f"/api/projects/{project['id']}"
    extract = client.post(base + "/runs", json={"stage": "extract"}, headers=headers)
    assert extract.status_code == 201, extract.text
    assert Worker(client.app.state.settings).run_once()
    run = client.post(base + "/runs", json={"stage": "separate"}, headers=headers)
    assert run.status_code == 201, run.text
    return run.json()


def stage_double(
    monkeypatch, client, tmp_path, *, fail_download=False, after_post=None, invalid=None
):
    import tempfile
    from pathlib import Path

    from sqlalchemy import select
    from test_multistem_audio import tone

    from videotranslate.models.analysis import PrivateOperation
    from videotranslate.providers.contracts import ProviderError

    audio = {
        kind: tone(tmp_path / f"remote-{kind}.wav", frequency, duration=2).read_bytes()
        for kind, frequency in (("drums", 220), ("bass", 440), ("vocals", 1760), ("other", 880))
    }

    class StageDouble(ProtocolDouble):
        failed = False
        polls, downloads = [], []

        def post_json(self, url, body, **kw):
            with client.app.state.session_factory() as db:
                op = db.scalar(
                    select(PrivateOperation).where(PrivateOperation.provider == "demucs_multistem")
                )
                assert (
                    op.phase == "submitting"
                    and op.model == "htdemucs"
                    and op.connection_revision == 1
                )
                assert op.host == PROFILE["endpoint"] and op.prefix == "/gradio_api"
                assert op.request_payload["profile"] == "demucs_multistem"
                assert op.request_payload["api_name"] == "process"
                assert op.request_payload["output_mapping"] == ["drums", "bass", "vocals", "other"]
            result = super().post_json(url, body, **kw)
            if after_post:
                after_post()
            return result

        def get_sse(self, url, **kw):
            self.polls.append(url)
            values = [
                {"path": f"/tmp/{stem}.wav", "meta": {"_type": "gradio.FileData"}} for stem in audio
            ]
            if invalid == "missing":
                values.pop()
            if invalid == "duplicate":
                values[-1] = values[0]
            return ("event: complete\ndata: " + json.dumps(values) + "\n\n").encode()

        def download(self, url, **kw):
            from urllib.parse import unquote

            stem = Path(unquote(url).split("file=")[1]).stem
            self.downloads.append(stem)
            with client.app.state.session_factory() as db:
                op = db.scalar(
                    select(PrivateOperation).where(PrivateOperation.provider == "demucs_multistem")
                )
                assert op.phase == "terminal" and len(op.terminal_payload) == 4
            if fail_download and stem == "other" and not self.failed:
                self.failed = True
                raise ProviderError("auth")  # Public artifact 403 is not token rotation.
            with tempfile.NamedTemporaryFile(delete=False) as out:
                out.write(b"invalid" if invalid == stem else audio[stem])
                return Path(out.name)

        def close(self):
            pass

    http = StageDouble()
    monkeypatch.setattr("videotranslate.dubbing.analysis.make_http", lambda _: http)
    return http


def test_registered_multistem_retries_saved_manifest_without_second_inference(
    dubbing_project, tmp_path, monkeypatch
):
    from sqlalchemy import select

    from videotranslate.execution.worker import Worker
    from videotranslate.models.analysis import PreparedObject, PrivateOperation
    from videotranslate.models.core import Asset
    from videotranslate.models.execution import StageRun

    client, headers, project = dubbing_project
    run = configured_run(dubbing_project)
    http = stage_double(monkeypatch, client, tmp_path, fail_download=True)
    assert Worker(client.app.state.settings).run_once()
    failed = client.get("/api/runs/" + run["id"]).json()
    assert failed["safe_error"]["code"] == "CONFIGURATION"
    with client.app.state.session_factory() as db:
        op = db.scalar(select(PrivateOperation).where(PrivateOperation.run_id == run["id"]))
        generation, remote_id = op.generation, op.remote_id
        assert op.phase == "terminal"
    retry = client.post("/api/runs/" + run["id"] + "/retry", headers=headers, json={})
    assert retry.status_code == 200, retry.text
    assert Worker(client.app.state.settings).run_once()
    done = client.get("/api/runs/" + run["id"]).json()
    assert done["status"] == "succeeded", done
    assert len([c for c in http.calls if c[0] == "post"]) == 1 and len(http.polls) == 1
    with client.app.state.session_factory() as db:
        op = db.scalar(select(PrivateOperation).where(PrivateOperation.run_id == run["id"]))
        assert op.generation == generation and op.remote_id == remote_id
        provenance = op.prepared_payload["provenance"]
        assert set(provenance["stems"]) == {"drums", "bass", "vocals", "other"}
        assert provenance["instrumental_sources"] == ["drums", "bass", "other"]
        assert len({data["sha256"] for data in provenance["stems"].values()}) == 4
        objects = db.scalars(
            select(PreparedObject).where(PreparedObject.operation_id == op.id)
        ).all()
        assert len(objects) == 2 and all(
            o.state == "published" and o.write_settled for o in objects
        )
        assets = db.scalars(
            select(Asset).where(
                Asset.project_id == project["id"], Asset.kind.in_(["vocals", "instrumental"])
            )
        ).all()
        assert {a.kind for a in assets} == {"vocals", "instrumental"}
        for asset in assets:
            with client.app.state.storage.open(asset.storage_key) as source:
                assert source.read(4) == b"RIFF"
        assert "stems" not in str(db.get(StageRun, run["id"]).result)


@pytest.mark.parametrize("invalid", ["missing", "duplicate", "other", "vocals"])
def test_invalid_four_stem_outputs_never_publish(dubbing_project, tmp_path, monkeypatch, invalid):
    from sqlalchemy import select

    from videotranslate.execution.worker import Worker
    from videotranslate.models.core import Asset

    client, _, project = dubbing_project
    run = configured_run(dubbing_project)
    http = stage_double(monkeypatch, client, tmp_path, invalid=invalid)
    assert Worker(client.app.state.settings).run_once()
    failed = client.get("/api/runs/" + run["id"]).json()
    assert failed["status"] == "failed" and failed["safe_error"]["code"] == "INVALID_MEDIA"
    assert failed["remote_id"] == "real-shaped-test-id"
    assert len([call for call in http.calls if call[0] == "post"]) == 1
    with client.app.state.session_factory() as db:
        assert not db.scalars(
            select(Asset).where(
                Asset.project_id == project["id"], Asset.kind.in_(["vocals", "instrumental"])
            )
        ).all()


def test_cancel_after_multistem_post_retains_id_and_prevents_poll_publish(
    dubbing_project, tmp_path, monkeypatch
):
    from sqlalchemy import select

    from videotranslate.execution.worker import Worker
    from videotranslate.models.analysis import PrivateOperation

    client, headers, _ = dubbing_project
    run = configured_run(dubbing_project)

    def cancel():
        assert (
            client.post("/api/runs/" + run["id"] + "/cancel", headers=headers, json={}).status_code
            == 200
        )

    http = stage_double(monkeypatch, client, tmp_path, after_post=cancel)
    assert Worker(client.app.state.settings).run_once()
    assert not http.polls and not http.downloads
    with client.app.state.session_factory() as db:
        op = db.scalar(select(PrivateOperation).where(PrivateOperation.run_id == run["id"]))
        assert op.remote_id == "real-shaped-test-id"


def test_metadata_check_only_validates_pinned_contract_and_never_claims_inference(
    client_factory, register, monkeypatch
):
    from videotranslate.providers.network import SafeHTTP

    client = client_factory()
    auth = register(client)
    headers = {"X-CSRF-Token": auth["csrf_token"]}
    assert client.put("/api/providers/separation", json=PROFILE, headers=headers).status_code == 200
    calls = []

    def get(self, url, **kw):
        calls.append(url)
        if "/api/spaces/" in url:
            return json.dumps({"host": PROFILE["endpoint"], "sha": SHA}).encode()
        return json.dumps(schema()).encode()

    monkeypatch.setattr(SafeHTTP, "get", get)
    check = client.post(
        "/api/providers/separation/check", json={"revision": 1}, headers=headers
    ).json()
    assert check["state"] == "reachable" and check["inference_verified"] is False
    assert check["capabilities"]["api_prefix"] == "/gradio_api"
    assert check["capabilities"]["api_name"] == "process"
    assert not any("whoami" in url for url in calls)


def test_preflight_float_limit_precedes_provider_http(dubbing_project, tmp_path, monkeypatch):
    from sqlalchemy import select

    from videotranslate.execution.worker import Worker
    from videotranslate.models.dubbing import SourceSelection

    client, _, _ = dubbing_project
    run = configured_run(dubbing_project)
    # Determinable projection alone suffices; no need to create a 200-second fixture.
    with client.app.state.session_factory.begin() as db:
        selection = db.scalar(select(SourceSelection))
        selection.end_ms = selection.start_ms + 200000
    http = stage_double(monkeypatch, client, tmp_path)
    assert Worker(client.app.state.settings).run_once()
    failed = client.get("/api/runs/" + run["id"]).json()
    assert failed["safe_error"]["code"] == "MEDIA_LIMIT"
    assert http.calls == [] and not http.polls


def test_settings_edit_after_paid_post_keeps_immutable_binding_and_suppresses_old_publish(
    dubbing_project, tmp_path, monkeypatch
):
    from sqlalchemy import select

    from videotranslate.execution.worker import Worker
    from videotranslate.models.analysis import PrivateOperation
    from videotranslate.models.core import Asset

    client, headers, project = dubbing_project
    run = configured_run(dubbing_project)

    def edit():
        assert (
            client.put(
                "/api/providers/separation",
                json={
                    "revision": 1,
                    "adapter": "demucs",
                    "model": "htdemucs_ft",
                    "space_id": "test/other",
                    "endpoint": "https://other.hf.space",
                },
                headers=headers,
            ).status_code
            == 200
        )

    http = stage_double(monkeypatch, client, tmp_path, after_post=edit)
    assert Worker(client.app.state.settings).run_once()
    assert not http.polls and not http.downloads
    with client.app.state.session_factory() as db:
        op = db.scalar(select(PrivateOperation).where(PrivateOperation.run_id == run["id"]))
        assert op.host == PROFILE["endpoint"] and op.connection_revision == 1
        assert op.request_payload["api_name"] == "process" and op.remote_id == "real-shaped-test-id"
        assert not db.scalars(
            select(Asset).where(
                Asset.project_id == project["id"], Asset.kind.in_(["vocals", "instrumental"])
            )
        ).all()


def test_multistem_private_cache_survives_publication_failure_and_same_input_retry(
    dubbing_project, tmp_path, monkeypatch
):
    from dataclasses import replace

    from sqlalchemy import select

    from videotranslate.execution.registry import STAGES
    from videotranslate.execution.worker import Worker
    from videotranslate.models.analysis import PrivateOperation
    from videotranslate.models.execution import StageRun

    client, headers, _ = dubbing_project
    run = configured_run(dubbing_project)
    http = stage_double(monkeypatch, client, tmp_path)

    def reject(*args):
        raise ValueError("test publication failure")

    registry = STAGES | {"separate": replace(STAGES["separate"], publish=reject)}
    assert Worker(client.app.state.settings, registry=registry).run_once()
    assert client.get("/api/runs/" + run["id"]).json()["status"] == "failed"
    with client.app.state.session_factory() as db:
        op = db.scalar(select(PrivateOperation).where(PrivateOperation.run_id == run["id"]))
        assert op.phase == "prepared"
        object_ids = op.prepared_payload["objects"]
        generation = op.generation
    assert (
        client.post("/api/runs/" + run["id"] + "/retry", headers=headers, json={}).status_code
        == 200
    )
    assert Worker(client.app.state.settings).run_once()
    with client.app.state.session_factory() as db:
        op = db.scalar(select(PrivateOperation).where(PrivateOperation.run_id == run["id"]))
        assert db.get(StageRun, run["id"]).status == "succeeded"
        assert op.generation == generation and op.prepared_payload["objects"] == object_ids
    assert len([c for c in http.calls if c[0] == "post"]) == 1 and len(http.polls) == 1
    assert len(http.downloads) == 4


def test_saved_legacy_operation_without_new_fields_polls_original_api(
    dubbing_project, tmp_path, monkeypatch
):
    import tempfile
    from datetime import timedelta
    from pathlib import Path

    from sqlalchemy import select
    from test_multistem_audio import tone

    from videotranslate.execution.context import RunContext
    from videotranslate.execution.prepared import Operations
    from videotranslate.execution.service import claim_run
    from videotranslate.execution.worker import Worker
    from videotranslate.models.core import utcnow
    from videotranslate.models.dubbing import SourceSelection
    from videotranslate.models.execution import StageRun

    client, _, _ = dubbing_project
    run = configured_run(dubbing_project)
    sf = client.app.state.session_factory
    with sf.begin() as db:
        lease = claim_run(db, "old-worker")
        selection = db.scalar(select(SourceSelection))
    ctx = RunContext(
        sf, client.app.state.storage, client.app.state.settings, run["id"], lease.lease_token
    )
    ops = Operations(ctx)
    ops.prepare(
        provider="demucs",
        model="htdemucs_ft",
        connection_revision=1,
        host="https://original.hf.space",
        prefix="",
        request_payload={"selection_id": selection.id, "duration_ms": 2000},
    )
    ops.begin()
    ops.accept("old-two-stem-id")
    with sf.begin() as db:
        db.get(StageRun, run["id"]).lease_expires_at = utcnow() - timedelta(seconds=1)
    data = tone(tmp_path / "legacy.wav", 220, duration=2).read_bytes()
    calls = []

    class LegacyDouble:
        allowed_hosts = set()

        def get_sse(self, url, **kw):
            calls.append(url)
            return b'event: complete\ndata: [{"path":"/tmp/v.wav"},{"path":"/tmp/i.wav"}]\n\n'

        def download(self, url, **kw):
            calls.append(url)
            with tempfile.NamedTemporaryFile(delete=False) as out:
                out.write(data)
                return Path(out.name)

        def close(self):
            pass

    monkeypatch.setattr("videotranslate.dubbing.analysis.make_http", lambda _: LegacyDouble())
    assert Worker(client.app.state.settings).run_once()
    assert client.get("/api/runs/" + run["id"]).json()["status"] == "succeeded"
    assert calls[0] == "https://original.hf.space/call/predict/old-two-stem-id"
    assert all("teamup" not in url for url in calls)


def test_public_artifact_failure_offers_result_review_and_download_only_retry(
    dubbing_project, tmp_path, monkeypatch
):
    from dubbing_helpers import selected
    from test_analysis_workflow import timeline

    from videotranslate.execution.worker import Worker

    client, headers, project = dubbing_project
    selected(dubbing_project)
    assert client.put("/api/providers/separation", json=PROFILE, headers=headers).status_code == 200
    base = f"/api/projects/{project['id']}"
    intent = client.post(
        base + "/workflow",
        headers=headers,
        json={
            "action": "prepare_media",
            "expected_editor_fingerprint": timeline(dubbing_project)["editor_fingerprint"],
        },
    ).json()
    worker = Worker(client.app.state.settings)
    assert worker.run_once()
    http = stage_double(monkeypatch, client, tmp_path, fail_download=True)
    assert worker.run_once()
    status = client.get(base + "/workflow/" + intent["id"]).json()
    assert status["status"] == "failed" and status["next_action"] == "review_separation_result"
    assert "token" not in str(status).lower()
    assert len([c for c in http.calls if c[0] == "post"]) == 1


@pytest.mark.parametrize("wrong_type", [None, [], "audio"])
def test_malformed_schema_types_are_configuration_errors(wrong_type):
    from videotranslate.providers.gradio import validate_endpoint_schema

    info = schema()
    info["named_endpoints"]["/process"]["returns"][0]["type"] = wrong_type
    with pytest.raises(ValueError, match="Incompatible"):
        validate_endpoint_schema(info, "demucs_multistem")


def test_metadata_check_rejects_host_drift_even_without_endpoint_override(
    client_factory, register, monkeypatch
):
    from videotranslate.providers.network import SafeHTTP

    client = client_factory()
    auth = register(client)
    headers = {"X-CSRF-Token": auth["csrf_token"]}
    assert (
        client.put(
            "/api/providers/separation", json=PROFILE | {"endpoint": None}, headers=headers
        ).status_code
        == 200
    )

    def get(self, url, **kw):
        if "/api/spaces/" in url:
            return json.dumps({"host": "https://other.hf.space", "sha": SHA}).encode()
        return json.dumps(schema()).encode()

    monkeypatch.setattr(SafeHTTP, "get", get)
    check = client.post(
        "/api/providers/separation/check", json={"revision": 1}, headers=headers
    ).json()
    assert check["state"] == "check_failed" and check["inference_verified"] is False

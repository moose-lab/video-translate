"""Owned URL import, restartable publication and SSRF boundary."""

import hashlib
import json

import httpx
import pytest
from sqlalchemy import select

from videotranslate.execution.worker import Worker
from videotranslate.models.execution import StageRun


def project(client_factory, register):
    client = client_factory()
    auth = register(client)
    headers = {"X-CSRF-Token": auth["csrf_token"]}
    row = client.post("/api/projects", json={"name": "Linked film"}, headers=headers).json()
    return client, headers, row


def endpoint(row):
    return f"/api/projects/{row['id']}/source-imports"


def install_http(monkeypatch, handler, resolver=None):
    from videotranslate.media import source_download

    original = source_download.PublicVideoHTTP
    monkeypatch.setattr(
        source_download,
        "make_http",
        lambda settings: original(
            transport=httpx.MockTransport(handler), resolver=resolver or (lambda _: ["8.8.8.8"])
        ),
    )


def test_admission_owned_private_pure_get_and_command_only(client_factory, register):
    client, headers, row = project(client_factory, register)
    url = "https://media.example/film.mp4?token=PRIVATE-SIGNED-TOKEN"
    body = {"url": url, "revision": row["revision"]}
    assert client.post(endpoint(row), json=body).status_code == 403
    response = client.post(endpoint(row), json=body, headers=headers)
    assert response.status_code == 202, response.text
    job = response.json()
    assert job["status"] == "queued" and job["source_asset_id"] is None
    assert "PRIVATE" not in json.dumps(job)
    for _ in range(2):
        assert client.get(endpoint(row)).json()["items"][0]["id"] == job["id"]
        assert client.get(endpoint(row) + "/" + job["id"]).json() == job
    with client.app.state.session_factory() as db:
        runs = db.scalars(select(StageRun)).all()
        assert len(runs) == 1 and runs[0].attempt_count == 0
        assert url not in json.dumps(runs[0].options)
        from videotranslate.models.source_import import SourceImport

        command = db.get(SourceImport, job["id"])
        assert "PRIVATE" not in command.encrypted_url
    direct = client.post(
        f"/api/projects/{row['id']}/runs",
        headers=headers,
        json={"stage": "source_import", "options": {"command_id": job["id"]}},
    )
    assert direct.status_code == 422
    other = client_factory(database_url=client.app.state.settings.database_url.get_secret_value())
    register(other, "other@example.com")
    assert other.get(endpoint(row) + "/" + job["id"]).status_code == 404


def test_import_streams_probes_publishes_owned_source_and_queues_probe(
    client_factory, register, monkeypatch, tiny_mp4
):
    client, headers, row = project(client_factory, register)
    calls = []

    def get(request):
        calls.append(str(request.url))
        return httpx.Response(200, content=tiny_mp4, headers={"Content-Type": "video/mp4"})

    install_http(monkeypatch, get)
    job = client.post(
        endpoint(row),
        json={"url": "https://media.example/v?secret=yes", "revision": row["revision"]},
        headers=headers,
    ).json()
    worker = Worker(client.app.state.settings)
    try:
        assert worker.run_once()
        done = client.get(endpoint(row) + "/" + job["id"]).json()
        assert done["status"] == "succeeded", done
        assert done["probe_run_id"] and done["source_asset_id"]
        asset = client.get(f"/api/projects/{row['id']}/assets").json()["items"][0]
        assert asset["sha256"] == hashlib.sha256(tiny_mp4).hexdigest()
        assert client.get(f"/api/assets/{asset['id']}/content").content == tiny_mp4
        assert worker.run_once()
        assert client.get(f"/api/runs/{done['probe_run_id']}").json()["status"] == "succeeded"
        assert calls == ["https://media.example/v?secret=yes"]
    finally:
        worker.engine.dispose()


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com/v.mp4",
        "https://localhost/v",
        "https://127.0.0.1/v",
        "https://[::1]/v",
        "https://user:pass@example.com/v",
        "file:///etc/passwd",
        "https://example.com:444/v",
        "https://example.com/v#fragment",
        "https://youtube.com.evil.example/watch?v=abcdefghijk",
        "https://www.youtube.com/playlist?list=xyz",
    ],
)
def test_reject_unsafe_or_non_video_youtube_input(client_factory, register, url):
    client, headers, row = project(client_factory, register)
    response = client.post(
        endpoint(row), json={"url": url, "revision": row["revision"]}, headers=headers
    )
    assert response.status_code == 422, response.text


def test_concurrent_upload_cannot_be_overwritten(client_factory, register, monkeypatch, tiny_mp4):
    client, headers, row = project(client_factory, register)

    def get(request):
        upload = client.post(
            f"/api/projects/{row['id']}/source",
            headers=headers,
            files={"file": ("manual.mp4", tiny_mp4, "video/mp4")},
        )
        assert upload.status_code == 201
        return httpx.Response(200, content=tiny_mp4)

    install_http(monkeypatch, get)
    job = client.post(
        endpoint(row),
        json={"url": "https://media.example/v", "revision": row["revision"]},
        headers=headers,
    ).json()
    worker = Worker(client.app.state.settings)
    try:
        worker.run_once()
        done = client.get(endpoint(row) + "/" + job["id"]).json()
        assert done["status"] == "stale", done
        assets = client.get(f"/api/projects/{row['id']}/assets").json()["items"]
        assert len(assets) == 1 and assets[0]["filename"] == "manual.mp4"
        retry = client.post(f"/api/runs/{job['run_id']}/retry", json={}, headers=headers)
        assert retry.status_code == 409
    finally:
        worker.engine.dispose()


def test_redirect_private_dns_and_size_caps(client_factory, register, monkeypatch):
    client, headers, row = project(client_factory, register)
    calls = []

    def get(request):
        calls.append(str(request.url))
        return httpx.Response(302, headers={"location": "https://private.example/x"})

    install_http(
        monkeypatch, get, lambda host: ["127.0.0.1"] if host == "private.example" else ["8.8.8.8"]
    )
    job = client.post(
        endpoint(row),
        json={"url": "https://media.example/v", "revision": row["revision"]},
        headers=headers,
    ).json()
    worker = Worker(client.app.state.settings)
    try:
        worker.run_once()
        done = client.get(endpoint(row) + "/" + job["id"]).json()
        assert done["status"] == "failed", done
        assert done["next_action"] == "upload_source"
        assert len(calls) == 1
    finally:
        worker.engine.dispose()


def test_prepared_import_recovers_after_lease_loss_without_redownload(
    client_factory, register, monkeypatch, tiny_mp4
):
    from datetime import timedelta

    from videotranslate.execution import worker as worker_module
    from videotranslate.execution.contracts import LeaseLost
    from videotranslate.models.core import utcnow

    client, headers, row = project(client_factory, register)
    calls = []

    def get(request):
        calls.append(request)
        return httpx.Response(200, content=tiny_mp4)

    install_http(monkeypatch, get)
    job = client.post(
        endpoint(row),
        json={"url": "https://media.example/v", "revision": row["revision"]},
        headers=headers,
    ).json()
    original = worker_module.finish_run

    def lose(*args, **kwargs):
        raise LeaseLost()

    monkeypatch.setattr(worker_module, "finish_run", lose)
    first = Worker(client.app.state.settings)
    first.run_once()
    first.engine.dispose()
    with client.app.state.session_factory.begin() as db:
        run = db.get(StageRun, job["run_id"])
        assert run.status == "running"
        run.lease_expires_at = utcnow() - timedelta(seconds=1)
    monkeypatch.setattr(worker_module, "finish_run", original)
    restarted = Worker(client.app.state.settings)
    try:
        restarted.run_once()
        done = client.get(endpoint(row) + "/" + job["id"]).json()
        assert done["status"] == "succeeded", done
        assert len(calls) == 1
        assert client.get(f"/api/projects/{row['id']}/assets").json()["total"] == 1
    finally:
        restarted.engine.dispose()


def test_cancelled_import_never_downloads_or_publishes(client_factory, register, monkeypatch):
    client, headers, row = project(client_factory, register)
    calls = []
    install_http(monkeypatch, lambda request: calls.append(request))
    job = client.post(
        endpoint(row),
        json={"url": "https://media.example/v", "revision": row["revision"]},
        headers=headers,
    ).json()
    response = client.post(f"/api/runs/{job['run_id']}/cancel", headers=headers)
    assert response.status_code == 200, response.text
    worker = Worker(client.app.state.settings)
    try:
        worker.run_once()
        assert client.get(endpoint(row) + "/" + job["id"]).json()["status"] == "cancelled"
        assert calls == []
        assert client.get(f"/api/projects/{row['id']}/assets").json()["total"] == 0
    finally:
        worker.engine.dispose()


def test_invalid_video_fails_without_asset(client_factory, register, monkeypatch):
    client, headers, row = project(client_factory, register)
    install_http(monkeypatch, lambda _: httpx.Response(200, content=b"<html>not a video</html>"))
    job = client.post(
        endpoint(row),
        json={"url": "https://media.example/v", "revision": row["revision"]},
        headers=headers,
    ).json()
    worker = Worker(client.app.state.settings)
    try:
        worker.run_once()
        done = client.get(endpoint(row) + "/" + job["id"]).json()
        assert done["status"] == "failed" and done["error"]["code"] == "INVALID_MEDIA"
        assert client.get(f"/api/projects/{row['id']}/assets").json()["total"] == 0
    finally:
        worker.engine.dispose()


@pytest.mark.parametrize(
    "format,content_type", [("mkv", "video/x-matroska"), ("avi", "video/x-msvideo")]
)
def test_supported_direct_containers_are_probed_not_mislabeled(
    client_factory, register, monkeypatch, tiny_mp4, tmp_path, format, content_type
):
    import subprocess

    original = tmp_path / "source.mp4"
    original.write_bytes(tiny_mp4)
    target = tmp_path / ("source." + format)
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(original),
            "-c:v",
            "mpeg4" if format == "avi" else "copy",
            str(target),
        ],
        check=True,
    )
    client, headers, row = project(client_factory, register)
    install_http(monkeypatch, lambda _: httpx.Response(200, content=target.read_bytes()))
    job = client.post(
        endpoint(row),
        json={"url": "https://media.example/v", "revision": row["revision"]},
        headers=headers,
    ).json()
    worker = Worker(client.app.state.settings)
    try:
        worker.run_once()
        done = client.get(endpoint(row) + "/" + job["id"]).json()
        assert done["status"] == "succeeded", done
        asset = client.get(f"/api/projects/{row['id']}/assets").json()["items"][0]
        assert asset["content_type"] == content_type
    finally:
        worker.engine.dispose()

"""Actual local stream-copy import from explicitly synthetic guarded HTTP parts."""

import hashlib
import json
import subprocess
import time
from types import SimpleNamespace

import httpx
import pytest
from test_source_imports import endpoint, install_http, project
from yt_dlp.extractor.youtube import YoutubeIE

from videotranslate.execution.contracts import CancellationRequested
from videotranslate.execution.worker import Worker


@pytest.fixture
def adaptive_parts(tmp_path, tiny_mp4):
    audio = tmp_path / "audio.m4a"
    subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=48000",
            "-t",
            "0.4",
            "-c:a",
            "aac",
            str(audio),
        ],
        check=True,
    )
    return tiny_mp4, audio.read_bytes()


def install_extractor(monkeypatch):
    monkeypatch.setattr(
        YoutubeIE,
        "_real_extract",
        lambda self, url: {
            "id": "abcdefghijk",
            "duration": 0.4,
            "formats": [
                {
                    "ext": "mp4",
                    "protocol": "https",
                    "vcodec": "avc1.64001f",
                    "acodec": "none",
                    "height": 720,
                    "url": "https://r1.googlevideo.com/video?signature=VIDEO-PRIVATE",
                },
                {
                    "ext": "mp4",
                    "protocol": "https",
                    "vcodec": "av01.0.08M.08",
                    "acodec": "none",
                    "height": 2160,
                    "url": "https://r1.googlevideo.com/too-large?signature=PRIVATE",
                },
                {
                    "ext": "m4a",
                    "protocol": "https",
                    "vcodec": "none",
                    "acodec": "mp4a.40.2",
                    "abr": 128,
                    "url": "https://r1.googlevideo.com/audio?signature=AUDIO-PRIVATE",
                },
            ],
        },
    )


def admit(client, headers, row):
    response = client.post(
        endpoint(row),
        headers=headers,
        json={"url": "https://www.youtube.com/watch?v=abcdefghijk", "revision": row["revision"]},
    )
    assert response.status_code == 202, response.text
    return response.json()


def test_adaptive_pair_uses_guarded_downloads_and_publishes_actual_playable_media(
    client_factory,
    register,
    monkeypatch,
    adaptive_parts,
    tmp_path,
    caplog,
):
    client, headers, row = project(client_factory, register)
    video, audio = adaptive_parts
    install_extractor(monkeypatch)
    calls = []

    def response(request):
        calls.append(request.url.path)
        assert "Cookie" not in request.headers and "Authorization" not in request.headers
        return httpx.Response(200, content={"/video": video, "/audio": audio}[request.url.path])

    install_http(monkeypatch, response)
    caplog.set_level("DEBUG")
    job = admit(client, headers, row)
    worker = Worker(client.app.state.settings)
    try:
        assert worker.run_once()
        done = client.get(endpoint(row) + "/" + job["id"]).json()
        assert done["status"] == "succeeded", done
        assert calls == ["/video", "/audio"]
        assets = client.get(f"/api/projects/{row['id']}/assets").json()["items"]
        assert len(assets) == 1
        asset = assets[0]
        raw = client.get(f"/api/assets/{asset['id']}/content").content
        assert len(raw) == asset["byte_size"]
        assert hashlib.sha256(raw).hexdigest() == asset["sha256"]
        output = tmp_path / "download.mp4"
        output.write_bytes(raw)
        probe = json.loads(
            subprocess.check_output(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-show_streams",
                    "-of",
                    "json",
                    str(output),
                ]
            )
        )
        assert {s["codec_type"] for s in probe["streams"]} == {"video", "audio"}
        subprocess.run(
            [
                "ffmpeg",
                "-nostdin",
                "-v",
                "error",
                "-xerror",
                "-i",
                str(output),
                "-map",
                "0",
                "-f",
                "null",
                "-",
            ],
            check=True,
        )
        assert worker.run_once()  # Ordinary durable probe of the published object.
        assert client.get(f"/api/runs/{done['probe_run_id']}").json()["status"] == "succeeded"
        assert "VIDEO-PRIVATE" not in caplog.text and "AUDIO-PRIVATE" not in caplog.text
    finally:
        worker.engine.dispose()


@pytest.mark.parametrize("failure", ["combined_cap", "audio_failure", "cancel_audio"])
def test_adaptive_partial_input_never_publishes(
    client_factory,
    register,
    monkeypatch,
    adaptive_parts,
    failure,
):
    video, audio = adaptive_parts
    client = client_factory(
        **({"upload_max_bytes": len(video) + len(audio) - 1} if failure == "combined_cap" else {})
    )
    auth = register(client)
    headers = {"X-CSRF-Token": auth["csrf_token"]}
    row = client.post("/api/projects", headers=headers, json={"name": "Pair failure"}).json()
    install_extractor(monkeypatch)
    job = admit(client, headers, row)

    def response(request):
        if request.url.path == "/audio":
            if failure == "audio_failure":
                return httpx.Response(503)
            if failure == "cancel_audio":
                cancelled = client.post(f"/api/runs/{job['run_id']}/cancel", headers=headers)
                assert cancelled.status_code == 202
            return httpx.Response(200, content=audio)
        return httpx.Response(200, content=video)

    install_http(monkeypatch, response)
    worker = Worker(client.app.state.settings)
    try:
        assert worker.run_once()
        done = client.get(endpoint(row) + "/" + job["id"]).json()
        assert done["status"] == ("cancelled" if failure == "cancel_audio" else "failed"), done
        assert done["source_asset_id"] is None and done["probe_run_id"] is None
        assert client.get(f"/api/projects/{row['id']}/assets").json()["items"] == []
        if failure == "combined_cap":
            assert done["error"]["code"] == "MEDIA_LIMIT"
    finally:
        worker.engine.dispose()


def test_pair_mux_reaps_its_child_on_cancellation(monkeypatch, adaptive_parts, tmp_path):
    from videotranslate.media import float_audio
    from videotranslate.media.source_download import PublicVideoHTTP
    from videotranslate.media.source_pair import download_pair
    from videotranslate.media.youtube_source import DownloadSpec

    video, audio = adaptive_parts
    http = PublicVideoHTTP(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(
                200,
                content=video if r.url.path == "/video" else audio,
            )
        ),
        resolver=lambda _: ["8.8.8.8"],
    )
    original, processes, commands = float_audio.subprocess.Popen, [], []

    def spawn(args, **kwargs):
        commands.append(args)
        result = original(args, **kwargs)
        processes.append(result)
        return result

    monkeypatch.setattr(float_audio.subprocess, "Popen", spawn)

    def check():
        if processes:
            raise CancellationRequested()

    work = tmp_path / "mux"
    work.mkdir()
    try:
        with pytest.raises(CancellationRequested):
            download_pair(
                http,
                DownloadSpec(
                    "https://r1.googlevideo.com/video", "https://r1.googlevideo.com/audio"
                ),
                work / "source.mp4",
                maximum=1024 * 1024,
                deadline=time.monotonic() + 10,
                check_active=check,
            )
        assert len(processes) == 1 and processes[0].poll() is not None
        assert commands[0].count("-protocol_whitelist") == 2
        assert commands[0].count("file,pipe") == 2
        assert not any("https://" in arg for arg in commands[0])
    finally:
        http.close()


def test_pair_probe_cannot_extend_the_original_import_deadline(
    client_factory,
    register,
    monkeypatch,
    adaptive_parts,
):
    from videotranslate.dubbing import source_import_execution
    from videotranslate.media import probe

    client, headers, row = project(client_factory, register)
    install_extractor(monkeypatch)
    video, audio = adaptive_parts
    install_http(
        monkeypatch,
        lambda r: httpx.Response(
            200,
            content=video if r.url.path == "/video" else audio,
        ),
    )
    now = time.monotonic()
    clock = [now]
    monkeypatch.setattr(
        source_import_execution, "time", SimpleNamespace(monotonic=lambda: clock[0])
    )

    def expired(context, path):
        clock[0] = now + 301
        context.check_active()
        raise AssertionError("The original import deadline was not enforced")

    monkeypatch.setattr(probe, "probe_path", expired)
    job = admit(client, headers, row)
    worker = Worker(client.app.state.settings)
    try:
        assert worker.run_once()
        done = client.get(endpoint(row) + "/" + job["id"]).json()
        assert done["status"] == "failed" and done["error"]["code"] == "MEDIA_LIMIT", done
        assert done["source_asset_id"] is None
    finally:
        worker.engine.dispose()

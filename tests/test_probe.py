"""Probe real CPU FFmpeg media; no inference runtimes are used."""

import importlib.util
import subprocess

import pytest

from videotranslate.execution.contracts import FailureCode, StageFailure


@pytest.fixture
def multi_audio(tmp_path):
    path = tmp_path / "two.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=48x32:r=5",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=400",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=800",
            "-map",
            "0:v",
            "-map",
            "1:a",
            "-map",
            "2:a",
            "-t",
            "0.4",
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            "-metadata:s:a:0",
            "language=eng",
            "-metadata:s:a:1",
            "language=jpn",
            str(path),
        ],
        check=True,
    )
    return path.read_bytes()


def test_real_probe_audio_ordinal_differs_from_stream_index(execution_project, multi_audio):
    assert importlib.util.find_spec("videotranslate.media.probe"), "Real probe missing"
    from videotranslate.execution.worker import Worker

    client, headers, project = execution_project
    client.post(
        f"/api/projects/{project['id']}/source",
        files={"file": ("two.mp4", multi_audio, "video/mp4")},
        headers=headers,
    )
    run = client.post(
        f"/api/projects/{project['id']}/runs", json={"stage": "probe"}, headers=headers
    ).json()
    assert Worker(client.app.state.settings).run_once() is True
    result = client.get(f"/api/runs/{run['id']}").json()
    assert result["status"] == "succeeded", result
    facts = result["result"]
    assert 300 <= facts["duration_ms"] <= 600
    assert facts["video"]["width"] == 48 and facts["video"]["height"] == 32
    assert [(a["audio_ordinal"], a["stream_index"], a["language"]) for a in facts["audio"]] == [
        (0, 1, "eng"),
        (1, 2, "jpn"),
    ]
    assert result["attempts"][0]["outcome"] == "succeeded"
    assert "storage_key" not in str(result) and "lease_token" not in str(result)


@pytest.mark.parametrize(
    "payload",
    [b"garbage", b"#EXTM3U\nhttp://127.0.0.1/private", b"ffconcat version 1.0\nfile /etc/passwd"],
)
def test_corrupt_and_playlist_sources_fail_explicitly(execution_project, payload):
    from videotranslate.execution.worker import Worker

    client, headers, project = execution_project
    client.post(
        f"/api/projects/{project['id']}/source",
        files={"file": ("fake.mp4", payload, "video/mp4")},
        headers=headers,
    )
    run = client.post(
        f"/api/projects/{project['id']}/runs", json={"stage": "probe"}, headers=headers
    ).json()
    Worker(client.app.state.settings).run_once()
    result = client.get(f"/api/runs/{run['id']}").json()
    assert result["status"] == "failed"
    assert result["safe_error"]["code"] == "INVALID_MEDIA"
    assert result["result"] is None


def test_probe_normalization_denies_nonfinite_and_excess_dimensions():
    from videotranslate.media.probe import normalize_probe

    for value in ["NaN", "inf", "-1"]:
        with pytest.raises(StageFailure):
            normalize_probe(
                {"format": {"duration": value}, "streams": []}, max_duration=60, max_pixels=10000
            )
    with pytest.raises(StageFailure) as error:
        normalize_probe(
            {
                "format": {"duration": "1"},
                "streams": [{"codec_type": "video", "width": 100000, "height": 100000}],
            },
            max_duration=60,
            max_pixels=10000,
        )
    assert error.value.code == FailureCode.MEDIA_LIMIT


def test_probe_timeout_kills_process_and_cleans_temporary_directory(
    execution_project, tmp_path, monkeypatch
):
    import videotranslate.media.probe as probe
    from videotranslate.execution.worker import Worker

    client, headers, project = execution_project
    run = client.post(
        f"/api/projects/{project['id']}/runs", json={"stage": "probe"}, headers=headers
    ).json()
    state = {"killed": False, "waited": False}

    class HungProcess:
        returncode = None

        def poll(self):
            return None if not state["killed"] else -9

        def kill(self):
            state["killed"] = True

        def wait(self):
            state["waited"] = True

    monkeypatch.setattr(probe.subprocess, "Popen", lambda *a, **k: HungProcess())
    monkeypatch.setattr(probe.tempfile, "tempdir", str(tmp_path))
    settings = client.app.state.settings.model_copy(update={"probe_timeout_seconds": 1})
    Worker(settings).run_once()
    assert state == {"killed": True, "waited": True}
    assert not list(tmp_path.glob("videotranslate-probe-*"))
    assert client.get(f"/api/runs/{run['id']}").json()["safe_error"]["code"] == "MEDIA_LIMIT"

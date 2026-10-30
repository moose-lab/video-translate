"""Recording HTTP transports and CPU fixtures; no provider inference or credentials."""

import json

import httpx
import pytest

from videotranslate.providers.contracts import ProviderError
from videotranslate.providers.network import SafeHTTP

URL = "https://example.hf.space"


def upload(http):
    return http.upload(
        URL + "/upload", filename="audio.wav", content=b"fixture", content_type="audio/wav"
    )


def test_only_multipart_upload_has_separate_bounded_timeout():
    requests = []

    def record(request):
        requests.append(request)
        return httpx.Response(200, json=["/tmp/audio.wav"])

    http = SafeHTTP(transport=httpx.MockTransport(record), resolver=lambda _: ["1.1.1.1"])
    try:
        # The same instance proves an upload cannot mutate later calls.
        assert upload(http) == ["/tmp/audio.wav"]
        http.get(URL + "/info")
        http.post_json(URL + "/call/process", {"data": []})
    finally:
        http.close()
    assert requests[0].extensions["timeout"] == {
        "connect": 5.0,
        "write": 120.0,
        "read": 30.0,
        "pool": 5.0,
    }
    assert requests[0].headers["content-type"].startswith("multipart/form-data;")
    for request in requests[1:]:
        assert request.extensions["timeout"] == {
            "connect": 5.0,
            "write": 15.0,
            "read": 15.0,
            "pool": 15.0,
        }
    assert all(request.headers["accept-encoding"] == "identity" for request in requests)


@pytest.mark.parametrize("failure", [httpx.WriteTimeout, httpx.ReadTimeout, httpx.ConnectError])
def test_upload_request_failure_is_network_and_never_retried(failure):
    requests = []

    def interrupt(request):
        requests.append(request)
        raise failure("private detail must stay out of errors", request=request)

    http = SafeHTTP(transport=httpx.MockTransport(interrupt), resolver=lambda _: ["1.1.1.1"])
    try:
        with pytest.raises(ProviderError) as error:
            upload(http)
        assert error.value.code == "network"
        assert "private detail" not in str(error.value)
        assert len(requests) == 1
        with pytest.raises(ProviderError) as error:
            http.post_json(URL + "/call/process", {"data": []})
        assert error.value.code == "uncertain"
        assert len(requests) == 2
    finally:
        http.close()


@pytest.mark.parametrize(
    "body",
    [b"not-json", b'{"event_id":"not-an-upload"}', b"[]", b"[null]", b'["https://x"]'],
)
def test_invalid_upload_response_is_preparation_failure(body):
    http = SafeHTTP(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, content=body)),
        resolver=lambda _: ["1.1.1.1"],
    )
    try:
        with pytest.raises(ProviderError) as error:
            upload(http)
        assert error.value.code == "invalid_response"
    finally:
        http.close()


def test_upload_response_limit_stops_stream_before_an_unbounded_body():
    class Oversized(httpx.SyncByteStream):
        def __iter__(self):
            yield b"x" * (1024 * 1024)
            yield b"x"
            raise AssertionError("read past upload response bound")

    http = SafeHTTP(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, stream=Oversized())),
        resolver=lambda _: ["1.1.1.1"],
    )
    try:
        with pytest.raises(ProviderError) as error:
            upload(http)
        assert error.value.code == "invalid_response"
    finally:
        http.close()


@pytest.mark.parametrize("body", [b"not-json", b"{}", b'{"event_id":"invalid id"}'])
def test_malformed_named_model_submission_remains_uncertain(body):
    from videotranslate.providers.gradio import GradioClient

    http = SafeHTTP(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, content=body)),
        resolver=lambda _: ["1.1.1.1"],
    )
    try:
        with pytest.raises(ProviderError) as error:
            GradioClient(http, URL, "/gradio_api").submit("process", [])
        assert error.value.code == "uncertain"
    finally:
        http.close()


def test_registered_worker_retries_upload_then_resumes_one_recorded_event(
    dubbing_project, tmp_path, monkeypatch
):
    from urllib.parse import unquote

    from sqlalchemy import select
    from test_demucs_multistem import PROFILE, SHA, configured_run, schema
    from test_multistem_audio import tone

    from videotranslate.execution.worker import Worker
    from videotranslate.models.analysis import PrivateOperation
    from videotranslate.models.core import utcnow
    from videotranslate.models.execution import StageRun

    client, _, _ = dubbing_project
    run_id = configured_run(dubbing_project)["id"]
    sf = client.app.state.session_factory
    requests, polls, event_ids = [], [], []
    uploads = 0
    download_failed = False
    files = [
        {"path": f"/tmp/{stem}.wav", "meta": {"_type": "gradio.FileData"}}
        for stem in ("drums", "bass", "vocals", "other")
    ]
    audio = {
        stem: tone(tmp_path / f"recorded-{stem}.wav", frequency, duration=2).read_bytes()
        for stem, frequency in (("drums", 220), ("bass", 440), ("vocals", 1760), ("other", 880))
    }

    def record(request):
        nonlocal uploads, download_failed
        requests.append((request.method, request.url.path))
        assert "authorization" not in request.headers
        path = request.url.path
        if path.startswith("/api/spaces/"):
            return httpx.Response(200, json={"host": PROFILE["endpoint"], "sha": SHA})
        if path == "/gradio_api/info":
            return httpx.Response(200, json=schema())
        if path == "/gradio_api/upload":
            uploads += 1
            with sf() as db:
                assert (
                    db.scalar(select(PrivateOperation).where(PrivateOperation.run_id == run_id))
                    is None
                )
            assert b"RIFF" in request.content  # The registered extract produced real WAV bytes.
            if uploads == 1:
                raise httpx.WriteTimeout("recorded upload interruption", request=request)
            return httpx.Response(200, json=["/tmp/recorded-upload.wav"])
        if path == "/gradio_api/call/process":
            assert request.method == "POST"
            with sf() as db:
                operation = db.scalar(
                    select(PrivateOperation).where(PrivateOperation.run_id == run_id)
                )
                assert operation.phase == "submitting" and operation.remote_id is None
                assert operation.request_payload["reference"]["path"] == "/tmp/recorded-upload.wav"
            assert json.loads(request.content)["data"][1] == "htdemucs"
            event_ids.append("recorded-event-1")
            return httpx.Response(200, json={"event_id": event_ids[-1]})
        if path == "/gradio_api/call/process/recorded-event-1":
            polls.append(path)
            if len(polls) == 1:
                return httpx.Response(200, content=b"event: heartbeat\ndata: null\n\n")
            return httpx.Response(
                200, content=("event: complete\ndata: " + json.dumps(files) + "\n\n").encode()
            )
        if path.startswith("/gradio_api/file="):
            with sf() as db:
                operation = db.scalar(
                    select(PrivateOperation).where(PrivateOperation.run_id == run_id)
                )
                assert operation.phase == "terminal"
                assert operation.terminal_payload == dict(zip(audio, files, strict=True))
            if not download_failed:
                download_failed = True
                return httpx.Response(503)
            stem = unquote(path).split("file=/tmp/", 1)[1].removesuffix(".wav")
            return httpx.Response(200, content=audio[stem])
        raise AssertionError("Unexpected recording transport request")

    monkeypatch.setattr(
        "videotranslate.dubbing.analysis.make_http",
        lambda _: SafeHTTP(transport=httpx.MockTransport(record), resolver=lambda _: ["1.1.1.1"]),
    )

    def work():
        # A new worker + HTTP client each time proves durable restart recovery.
        worker = Worker(client.app.state.settings)
        try:
            assert worker.run_once()
        finally:
            worker.engine.dispose()

    def due():
        with sf.begin() as db:
            db.get(StageRun, run_id).due_at = utcnow()

    work()
    with sf() as db:
        run = db.get(StageRun, run_id)
        assert run.status == "retry_wait" and run.auto_failures == 1
        assert run.safe_error == {"code": "TRANSIENT", "retryable": True}
        assert run.remote_state == "not_submitted" and run.remote_id is None
        assert db.scalar(select(PrivateOperation).where(PrivateOperation.run_id == run_id)) is None
    assert uploads == 1 and event_ids == [] and polls == []
    due()
    work()
    with sf() as db:
        operation = db.scalar(select(PrivateOperation).where(PrivateOperation.run_id == run_id))
        operation_id, generation = operation.id, operation.generation
        assert operation.phase == "accepted" and operation.remote_id == event_ids[0]
        assert db.get(StageRun, run_id).remote_id == event_ids[0]
    assert uploads == 2 and event_ids == ["recorded-event-1"]
    due()
    work()
    with sf() as db:
        operation = db.get(PrivateOperation, operation_id)
        assert operation.phase == "terminal" and operation.remote_id == event_ids[0]
        assert operation.terminal_payload == dict(zip(audio, files, strict=True))
        assert db.get(StageRun, run_id).status == "retry_wait"
    due()
    work()
    with sf() as db:
        operation = db.get(PrivateOperation, operation_id)
        assert operation.generation == generation and operation.remote_id == event_ids[0]
        assert db.get(StageRun, run_id).status == "succeeded"
    assert uploads == 2 and event_ids == ["recorded-event-1"] and len(polls) == 2
    assert requests.count(("POST", "/gradio_api/call/process")) == 1

"""Transport policy evidence using HTTPX requests, never real provider inference."""

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Event

import httpx
import pytest
from sqlalchemy import select
from test_translation_operations import (
    RecordingChat,
    drain,
    request_body,
    set_mode,
    view,
)
from test_translation_operations import (
    translation_project as translation_project,
)

from videotranslate.execution.worker import Worker
from videotranslate.models.analysis import PrivateOperation
from videotranslate.models.core import utcnow
from videotranslate.models.execution import StageRun
from videotranslate.providers.chat import structured_chat
from videotranslate.providers.contracts import ProviderError
from videotranslate.providers.network import SafeHTTP

CHAT_TIMEOUT = {"connect": 5.0, "write": 30.0, "read": 180.0, "pool": 5.0}
DEFAULT_TIMEOUT = {"connect": 5.0, "write": 15.0, "read": 15.0, "pool": 15.0}
UPLOAD_TIMEOUT = {"connect": 5.0, "write": 120.0, "read": 30.0, "pool": 5.0}
URL = "https://router.huggingface.co/v1/chat/completions"


def envelope():
    return {
        "id": "actual-recorded-id",
        "usage": {"total_tokens": 7},
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {"target_language": "ja", "segments": [{"id": "a", "text": "訳文"}]}
                    )
                }
            }
        ],
    }


def chat(http, **kwargs):
    return structured_chat(
        http,
        model="recorded-model",
        token="test-only-token",
        target="ja",
        segments=[{"id": "a", "text": "private-dialogue"}],
        **kwargs,
    )


def test_chat_policy_is_per_request_without_contaminating_default_or_upload():
    seen = []

    def record(request):
        seen.append(request)
        if request.url.path == "/upload":
            return httpx.Response(200, json=["/tmp/upload/reference.wav"])
        return httpx.Response(200, json=envelope())

    with_http = SafeHTTP(transport=httpx.MockTransport(record), resolver=lambda _: ["1.1.1.1"])
    try:
        result = chat(
            with_http,
            context={"timeout": {"read": 0}, "_timeout_profile": "untrusted"},
            glossary={"timeout": "unbounded"},
        )
        with_http.post_json(URL, {"timeout": {"read": None}})
        with_http.get("https://huggingface.co/api/models/test")
        with_http.upload(
            "https://example.hf.space/upload",
            filename="reference.wav",
            content=b"recorded-audio",
            content_type="audio/wav",
        )
        assert result["segments"] == {"a": "訳文"}
        assert result["metadata"] == {
            "response_id": "actual-recorded-id",
            "usage": {"total_tokens": 7},
        }
        assert [r.extensions["timeout"] for r in seen] == [
            CHAT_TIMEOUT,
            DEFAULT_TIMEOUT,
            DEFAULT_TIMEOUT,
            UPLOAD_TIMEOUT,
        ]
        assert with_http.client.timeout == httpx.Timeout(15.0, connect=5.0)
        body = json.loads(seen[0].content)
        assert set(body) == {"model", "messages", "response_format"}
        assert json.loads(body["messages"][1]["content"])["quoted_data"]["context"]["timeout"] == {
            "read": 0
        }
    finally:
        with_http.close()


@pytest.mark.parametrize("profile", ["unknown", "", 180, True, {}, {"read": 180}, [], object()])
def test_invalid_private_profile_rejected_before_resolver_or_network(profile):
    seen = []
    http = SafeHTTP(
        transport=httpx.MockTransport(lambda request: seen.append("network")),
        resolver=lambda _: seen.append("resolver"),
    )
    try:
        with pytest.raises(ValueError, match="Invalid provider timeout profile"):
            http.post_json(URL, {}, _timeout_profile=profile)
        assert seen == []
    finally:
        http.close()


class Interrupted(httpx.SyncByteStream):
    def __iter__(self):
        yield b'{"choices":'
        raise httpx.ReadError("test-only-token private-dialogue provider-secret")


@pytest.mark.parametrize(
    "failure,code",
    [
        ("timeout", "uncertain"),
        ("interrupted", "uncertain"),
        ("encoded", "uncertain"),
        ("oversized", "uncertain"),
        ("malformed", None),
        (401, "auth"),
        (429, "quota"),
        (422, "configuration"),
        (503, "network"),
        (302, "network"),
    ],
)
def test_chat_failures_are_single_submissions_and_sanitized(failure, code, caplog):
    seen = []

    def record(request):
        seen.append(request)
        assert request.extensions["timeout"] == CHAT_TIMEOUT
        if failure == "timeout":
            raise httpx.ReadTimeout("test-only-token private-dialogue provider-secret")
        if failure == "interrupted":
            return httpx.Response(200, stream=Interrupted())
        if failure == "encoded":
            return httpx.Response(200, headers={"content-encoding": "gzip"}, content=b"bad")
        if failure == "oversized":
            return httpx.Response(200, content=b"x" * (1024 * 1024 + 1))
        if failure == "malformed":
            return httpx.Response(200, content=b"provider-secret")
        return httpx.Response(
            failure, content=b"provider-secret", headers={"location": "https://evil.example"}
        )

    http = SafeHTTP(transport=httpx.MockTransport(record), resolver=lambda _: ["1.1.1.1"])
    try:
        with pytest.raises(ValueError) as error:
            chat(http)
        assert len(seen) == 1 and seen[0].method == "POST" and str(seen[0].url) == URL
        if code:
            assert isinstance(error.value, ProviderError) and error.value.code == code
        else:
            assert str(error.value) == "Invalid structured translation response"
        assert len(str(error.value)) < 100
        for private in ("test-only-token", "private-dialogue", "provider-secret", "Authorization"):
            assert private not in str(error.value) + caplog.text
    finally:
        http.close()


class WorkerTransport:
    """Real SafeHTTP/HTTPX request recording around deterministic translation fixtures."""

    def __init__(self, monkeypatch):
        self.requests = []
        self.responses = RecordingChat()
        self.fail_phase = None
        self.hook = None
        monkeypatch.setattr("videotranslate.dubbing.remote_translation.make_http", self.make_http)

    def make_http(self, context):
        return SafeHTTP(
            allowed_hosts={"translator.example"},
            transport=httpx.MockTransport(self.handle),
            resolver=lambda _: ["1.1.1.1"],
        )

    def handle(self, request):
        body = json.loads(request.content)
        phase = body["messages"][0]["content"].split("Phase: ")[1].split(".")[0]
        self.requests.append((phase, request))
        assert request.method == "POST"
        assert str(request.url) == "https://translator.example/v1/chat/completions"
        assert request.extensions["timeout"] == CHAT_TIMEOUT
        if self.hook:
            self.hook(phase)
        if phase == self.fail_phase:
            raise httpx.ReadTimeout("provider-secret private-dialogue test-only-token")
        return httpx.Response(200, content=self.responses.post_json(str(request.url), body))


@pytest.mark.parametrize("lost_phase", ["context", "draft", "critique", "rewrite"])
def test_registered_worker_chat_wait_preserves_phase_retry_history(
    translation_project, monkeypatch, lost_phase, caplog
):
    c, h, p, s, line, track = translation_project
    transport = WorkerTransport(monkeypatch)
    transport.fail_phase = lost_phase
    track = set_mode(c, h, p, track, "Cinematic")
    path = f"/api/projects/{p['id']}/language-tracks/zh-Hant/translate"
    sf = c.app.state.session_factory
    with sf() as db:
        original_non_translation = [
            run.id
            for run in db.scalars(select(StageRun))
            if not run.stage.startswith("translation_")
        ]
    queued = c.post(path, headers=h, json=request_body(s, line, track))
    assert queued.status_code == 202, queued.text
    drain(c)
    state = c.get(path + "/" + queued.json()["id"]).json()
    phases = ["context", "draft", "critique", "rewrite"]
    expected = phases[: phases.index(lost_phase) + 1]
    assert [phase for phase, _ in transport.requests] == expected
    assert state["next_action"] == "acknowledge_uncertain_submission"
    failed_id = state["phases"][-1]["run_id"]
    with sf() as db:
        old = db.scalar(select(PrivateOperation).where(PrivateOperation.run_id == failed_id))
        old_id, old_generation = old.id, old.generation
        assert old.phase == "submitting"
        prepared_ids = {
            op.id for op in db.scalars(select(PrivateOperation)) if op.phase == "prepared"
        }
        assert len(prepared_ids) == len(expected) - 1
    assert c.post(f"/api/runs/{failed_id}/retry", headers=h, json={}).status_code == 409
    drain(c)
    assert len(transport.requests) == len(expected)
    transport.fail_phase = None
    ack = c.post(
        f"/api/runs/{failed_id}/retry",
        headers=h,
        json={"acknowledge_uncertain_submission": True},
    )
    assert ack.status_code == 200, ack.text
    drain(c)
    assert [phase for phase, _ in transport.requests] == expected + phases[
        phases.index(lost_phase) :
    ]
    assert c.get(path + "/" + queued.json()["id"]).json()["status"] == "review"
    assert view(c, p, line)["text"] == "IBM 製造電腦。"
    assert view(c, p, line)["approved"] is False
    with sf() as db:
        operations = db.scalars(select(PrivateOperation)).all()
        old = db.get(PrivateOperation, old_id)
        assert old.phase == "submitting" and old.generation == old_generation
        new = [op for op in operations if op.run_id == failed_id and op.id != old_id]
        assert len(new) == 1 and new[0].phase == "prepared"
        assert new[0].generation != old_generation
        assert prepared_ids <= {op.id for op in operations if op.phase == "prepared"}
        assert len({op.run_id for op in operations}) == 4
        assert all("timeout" not in json.dumps(op.request_payload) for op in operations)
        assert original_non_translation == [
            run.id
            for run in db.scalars(select(StageRun))
            if not run.stage.startswith("translation_")
        ]
    public = json.dumps(c.get(f"/api/projects/{p['id']}/events").json()) + json.dumps(state)
    for private in ("provider-secret", "private-dialogue", "test-only-token"):
        assert private not in public + caplog.text


def test_registered_phases_checkpoint_privately_before_publication_and_reuse(
    translation_project, monkeypatch
):
    from videotranslate.execution import worker as worker_module

    c, h, p, s, line, track = translation_project
    transport = WorkerTransport(monkeypatch)
    track = set_mode(c, h, p, track, "Cinematic")
    path = f"/api/projects/{p['id']}/language-tracks/zh-Hant/translate"
    body = request_body(s, line, track)
    queued = c.post(path, headers=h, json=body)
    assert queued.status_code == 202
    checkpoints = []
    original_finish = worker_module.finish_run

    def finish(db, run_id, lease_token, result, **kwargs):
        # Read through an independent session: the prepared checkpoint is already committed.
        with c.app.state.session_factory() as observer:
            run = observer.get(StageRun, run_id)
            op = observer.get(PrivateOperation, result.prepared_id)
            assert run.status == "running"
            assert op.run_id == run_id and op.phase == "prepared" and op.prepared_payload
            assert op.generation == run.request_key
            assert "timeout" not in json.dumps(op.request_payload)
            assert "timeout" not in json.dumps(run.options)
            checkpoints.append((run.stage, op.id, op.input_fingerprint))
        return original_finish(db, run_id, lease_token, result, **kwargs)

    monkeypatch.setattr(worker_module, "finish_run", finish)
    drain(c)
    assert [stage for stage, _, _ in checkpoints] == [
        "translation_context",
        "translation_draft",
        "translation_critique",
        "translation_rewrite",
    ]
    assert len({op_id for _, op_id, _ in checkpoints}) == 4
    assert len(transport.requests) == 4
    body["segments"][0]["revision"] = view(c, p, line)["revision"]
    replay = c.post(path, headers=h, json=body)
    assert replay.status_code == 202 and replay.json()["id"] == queued.json()["id"]
    drain(c)
    assert len(transport.requests) == 4 and len(checkpoints) == 4


def test_pre_policy_prepared_translation_survives_restart_without_new_post(
    translation_project, monkeypatch
):
    from videotranslate.dubbing.remote_translation import handler
    from videotranslate.execution.context import RunContext
    from videotranslate.execution.service import claim_run

    c, h, p, s, line, track = translation_project
    recorded = RecordingChat()
    requests = []

    def record(request):
        requests.append(request)
        assert request.extensions["timeout"] == DEFAULT_TIMEOUT
        return httpx.Response(
            200, content=recorded.post_json(str(request.url), json.loads(request.content))
        )

    class PrePolicyHTTP(SafeHTTP):
        def post_json(self, *args, **kwargs):
            kwargs.pop("_timeout_profile", None)  # Test the previous transport policy only.
            return super().post_json(*args, **kwargs)

    monkeypatch.setattr(
        "videotranslate.dubbing.remote_translation.make_http",
        lambda _: PrePolicyHTTP(
            allowed_hosts={"translator.example"},
            transport=httpx.MockTransport(record),
            resolver=lambda _: ["1.1.1.1"],
        ),
    )
    path = f"/api/projects/{p['id']}/language-tracks/zh-Hant/translate"
    queued = c.post(path, headers=h, json=request_body(s, line, track))
    assert queued.status_code == 202
    sf = c.app.state.session_factory
    with sf.begin() as db:
        run = claim_run(db, "pre-policy-worker")
    result = handler(
        RunContext(sf, c.app.state.storage, c.app.state.settings, run.id, run.lease_token)
    )
    with sf.begin() as db:
        operation = db.get(PrivateOperation, result.prepared_id)
        identity = (operation.id, operation.generation, operation.input_fingerprint)
        assert operation.phase == "prepared"
        db.get(StageRun, run.id).lease_expires_at = utcnow() - timedelta(seconds=1)
    # The ordinary post-policy factory is installed, but a durable cache must avoid it entirely.
    resumed_transport = WorkerTransport(monkeypatch)
    assert Worker(c.app.state.settings).run_once()
    assert len(requests) == 1 and resumed_transport.requests == []
    with sf() as db:
        operation = db.get(PrivateOperation, result.prepared_id)
        assert (operation.id, operation.generation, operation.input_fingerprint) == identity
        assert db.get(StageRun, run.id).status == "succeeded"
    assert view(c, p, line)["text"] == "IBM 製造電腦產品。"


@pytest.mark.parametrize("lose_lease", [False, True])
def test_blocked_chat_keeps_real_heartbeat_and_fences_lost_lease(
    translation_project, monkeypatch, lose_lease
):
    from videotranslate.execution import worker as worker_module

    c, h, p, s, line, track = translation_project
    transport = WorkerTransport(monkeypatch)
    path = f"/api/projects/{p['id']}/language-tracks/zh-Hant/translate"
    queued = c.post(path, headers=h, json=request_body(s, line, track))
    assert queued.status_code == 202
    run_id = queued.json()["phases"][0]["run_id"]
    entered, release, pulses = Event(), Event(), Event()
    heartbeat_count = 0
    original_heartbeat = worker_module.heartbeat

    def heartbeat(*args):
        nonlocal heartbeat_count
        result = original_heartbeat(*args)
        if result:
            heartbeat_count += 1
            if heartbeat_count >= 4:
                pulses.set()
        return result

    def block(phase):
        entered.set()
        assert release.wait(10), "test controller did not release recorded HTTP response"

    transport.hook = block
    monkeypatch.setattr(worker_module, "heartbeat", heartbeat)
    settings = c.app.state.settings.model_copy(
        update={"worker_lease_seconds": 3, "worker_heartbeat_seconds": 1}
    )
    worker = Worker(settings)
    try:
        with ThreadPoolExecutor(1) as pool:
            future = pool.submit(worker.run_once)
            try:
                assert entered.wait(5)
                with c.app.state.session_factory() as db:
                    run = db.get(StageRun, run_id)
                    original_expiry = run.lease_expires_at
                assert pulses.wait(7), "worker failed to heartbeat during the blocked response"
                with c.app.state.session_factory.begin() as db:
                    run = db.get(StageRun, run_id)
                    assert run.status == "running" and not future.done()
                    assert original_expiry < utcnow() < run.lease_expires_at
                    assert run.heartbeat_at > original_expiry
                    op = db.scalar(
                        select(PrivateOperation).where(PrivateOperation.run_id == run_id)
                    )
                    assert op.phase == "submitting" and op.prepared_payload is None
                    if lose_lease:
                        run.lease_token = "different-worker-lease"
                assert view(c, p, line) is None
            finally:
                release.set()
            assert future.result(timeout=5)
        assert len(transport.requests) == 1
        with c.app.state.session_factory() as db:
            run = db.get(StageRun, run_id)
            op = db.scalar(select(PrivateOperation).where(PrivateOperation.run_id == run_id))
            if lose_lease:
                assert run.status == "running" and op.phase == "submitting"
                assert op.prepared_payload is None and view(c, p, line) is None
            else:
                assert run.status == "succeeded" and op.phase == "prepared"
                assert view(c, p, line)["text"] == "IBM 製造電腦產品。"
                assert view(c, p, line)["approved"] is False
    finally:
        worker.engine.dispose()

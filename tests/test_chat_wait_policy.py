"""Transport policy evidence using HTTPX requests, never real provider inference."""

import json

import httpx
import pytest

from videotranslate.providers.hf_router import structured_chat, translate
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


def test_legacy_translation_keeps_body_result_and_default_policy():
    seen = []

    def record(request):
        seen.append(request)
        return httpx.Response(200, json=envelope())

    http = SafeHTTP(transport=httpx.MockTransport(record), resolver=lambda _: ["1.1.1.1"])
    try:
        assert translate(
            http, model="m", token="t", target="ja", segments=[{"id": "a", "text": "A"}]
        ) == {"a": "訳文"}
        assert seen[0].extensions["timeout"] == DEFAULT_TIMEOUT
        assert json.loads(json.loads(seen[0].content)["messages"][1]["content"]) == {
            "target_language": "ja",
            "segments": [{"id": "a", "text": "A"}],
        }
    finally:
        http.close()

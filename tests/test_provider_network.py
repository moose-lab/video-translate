import pytest


def test_url_policy_denies_private_credentials_non_https_and_unknown_hosts():
    from videotranslate.providers.network import validate_url

    assert validate_url("https://router.huggingface.co/v1") == "https://router.huggingface.co/v1"
    for url in [
        "http://router.huggingface.co/",
        "https://user:pass@router.huggingface.co/",
        "https://router.huggingface.co/#fragment",
        "https://127.0.0.1/",
        "https://evil.example/",
        "https://router.huggingface.co:444/",
        "https://router.huggingface.co/?token=secret",
        "file:///tmp/audio",
    ]:
        with pytest.raises(ValueError):
            validate_url(url)
    assert (
        validate_url("https://custom.example/v1", allowed_hosts={"custom.example"})
        == "https://custom.example/v1"
    )


def test_checked_redirect_drops_auth_and_limits_response():
    import httpx

    from videotranslate.providers.network import SafeHTTP

    seen = []

    def handler(request):
        seen.append(request)
        if len(seen) == 1:
            return httpx.Response(302, headers={"location": "https://example.hf.space/info"})
        return httpx.Response(200, content=b"ok")

    client = SafeHTTP(transport=httpx.MockTransport(handler), resolver=lambda host: ["1.1.1.1"])
    response = client.get(
        "https://huggingface.co/api/spaces/example",
        headers={"Authorization": "Bearer fake"},
        max_bytes=20,
    )
    assert response == b"ok"
    assert "authorization" in seen[0].headers
    assert "authorization" not in seen[1].headers
    client.close()
    client = SafeHTTP(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, content=b"x" * 11)),
        resolver=lambda host: ["1.1.1.1"],
    )
    with pytest.raises(ValueError):
        client.get("https://huggingface.co/api/spaces/example", max_bytes=10)
    client.close()


def test_post_ambiguous_failure_never_retries():
    import httpx

    from videotranslate.providers.network import SafeHTTP

    calls = []

    def handler(request):
        calls.append(request)
        raise httpx.ReadTimeout("sensitive provider response")

    client = SafeHTTP(transport=httpx.MockTransport(handler), resolver=lambda host: ["1.1.1.1"])
    with pytest.raises(ValueError, match="uncertain"):
        client.post_json("https://example.hf.space/call/predict", {"data": ["example"]})
    assert len(calls) == 1
    client.close()


def test_multipart_upload_is_bounded_and_not_retried():
    import httpx

    from videotranslate.providers.network import SafeHTTP

    captured = []

    def handler(request):
        captured.append(request)
        return httpx.Response(200, json=["/tmp/upload/reference.wav"])

    client = SafeHTTP(transport=httpx.MockTransport(handler), resolver=lambda host: ["1.1.1.1"])
    result = client.upload(
        "https://example.hf.space/upload",
        filename="reference.wav",
        content=b"fake-audio",
        content_type="audio/wav",
    )
    assert result == ["/tmp/upload/reference.wav"]
    assert len(captured) == 1
    assert b"fake-audio" in captured[0].content
    with pytest.raises(ValueError):
        client.upload(
            "https://example.hf.space/upload",
            filename="../x.wav",
            content=b"example",
            content_type="audio/wav",
        )
    client.close()


def test_provider_http_errors_are_categorized_without_response_content():
    import httpx

    from videotranslate.providers.contracts import ProviderError
    from videotranslate.providers.network import SafeHTTP

    for status, code in [
        (401, "auth"),
        (403, "auth"),
        (429, "quota"),
        (404, "configuration"),
        (503, "network"),
    ]:
        client = SafeHTTP(
            transport=httpx.MockTransport(
                lambda request, code=status: httpx.Response(code, text="secret provider body")
            ),
            resolver=lambda host: ["1.1.1.1"],
        )
        with pytest.raises(ProviderError) as error:
            client.get("https://huggingface.co/api/models/test")
        assert error.value.code == code
        assert "secret provider body" not in str(error.value)
        client.close()


def test_sse_read_stops_after_terminal_event_without_waiting_for_stream_close():
    import httpx

    from videotranslate.providers.network import SafeHTTP

    class Stream(httpx.SyncByteStream):
        def __iter__(self):
            yield b"event: heartbeat\ndata: null\n\n"
            yield b"event: complete\ndata: [1]\n\n"
            raise AssertionError("must stop after terminal event")

    client = SafeHTTP(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, stream=Stream())),
        resolver=lambda host: ["1.1.1.1"],
    )
    assert b"event: complete" in client.get_sse("https://test.hf.space/call/predict/id")
    client.close()


def test_admin_proxy_connects_only_to_validated_public_ip_without_provider_headers(monkeypatch):
    import socket

    from videotranslate.providers.network import open_proxy_tunnel

    class Socket:
        def __init__(self):
            self.sent = b""

        def sendall(self, data):
            self.sent += data

        def recv(self, size):
            return b"HTTP/1.1 200 Connection established\r\n\r\n"

        def settimeout(self, value):
            pass

        def close(self):
            pass

    sock = Socket()
    addresses = []

    def connect(address, timeout):
        addresses.append(address)
        return sock

    monkeypatch.setattr(socket, "create_connection", connect)
    result = open_proxy_tunnel("http://127.0.0.1:7897", "1.1.1.1", 443, 5)
    assert result is sock
    assert addresses == [("127.0.0.1", 7897)]
    assert sock.sent.startswith(b"CONNECT 1.1.1.1:443 HTTP/1.1\r\n")
    assert b"Authorization: Bearer" not in sock.sent
    with pytest.raises(ValueError):
        open_proxy_tunnel("http://127.0.0.1:7897", "127.0.0.1", 443, 5)


def test_doh_accepts_only_public_answers_and_does_not_send_provider_secret():
    from videotranslate.providers.network import resolve_doh

    calls = []

    def query(proxy, host, record_type):
        calls.append((proxy, host, record_type))
        return (
            {"Status": 0, "Answer": [{"type": 1, "data": "1.1.1.1"}]}
            if record_type == "A"
            else {"Status": 0, "Answer": []}
        )

    assert resolve_doh("router.huggingface.co", "http://127.0.0.1:7897", query=query) == ["1.1.1.1"]
    assert [x[2] for x in calls] == ["A", "AAAA"]
    with pytest.raises(ValueError):
        resolve_doh(
            "example.hf.space",
            "http://127.0.0.1:7897",
            query=lambda *args: {"Status": 0, "Answer": [{"type": 1, "data": "127.0.0.1"}]},
        )


def test_proxy_backend_pins_dns_target_and_keeps_origin_for_tls(monkeypatch):
    from videotranslate.providers import network

    calls = []

    class Socket:
        def close(self):
            pass

    monkeypatch.setattr(
        network,
        "open_proxy_tunnel",
        lambda proxy, ip, port, timeout: (calls.append((proxy, ip, port)), Socket())[1],
    )
    client = network.SafeHTTP(
        proxy_url="http://127.0.0.1:7897", resolver=lambda hostname: ["1.1.1.1"]
    )
    backend = client.client._transport._pool._network_backend
    stream = backend.connect_tcp("router.huggingface.co", 443, timeout=5)
    assert calls == [("http://127.0.0.1:7897", "1.1.1.1", 443)]
    stream.close()
    client.close()


def test_encoded_responses_are_rejected_before_decompression_for_all_operations():
    import httpx

    from videotranslate.providers.contracts import ProviderError
    from videotranslate.providers.network import SafeHTTP

    class NeverRead(httpx.SyncByteStream):
        def __iter__(self):
            raise AssertionError("compressed body must not be read")
            yield b""

    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, headers={"Content-Encoding": "gzip"}, stream=NeverRead())

    client = SafeHTTP(transport=httpx.MockTransport(handler), resolver=lambda host: ["1.1.1.1"])
    url = "https://example.hf.space/file"
    operations = [
        (
            lambda: client.get(url, headers={"Accept-Encoding": "gzip"}, max_bytes=1024),
            "invalid_response",
        ),
        (lambda: client.get_sse(url, max_bytes=1024), "invalid_response"),
        (lambda: client.download(url, max_bytes=1024), "invalid_response"),
        (lambda: client.post_json(url, {"data": []}, max_bytes=1024), "uncertain"),
        (
            lambda: client.upload(
                url, filename="test.wav", content=b"fake", content_type="audio/wav"
            ),
            "uncertain",
        ),
    ]
    for operation, expected in operations:
        with pytest.raises(ProviderError) as error:
            operation()
        assert error.value.code == expected
    assert all(request.headers["accept-encoding"] == "identity" for request in seen)
    client.close()


def test_oversized_or_invalid_successful_post_response_is_uncertain():
    import httpx

    from videotranslate.providers.contracts import ProviderError
    from videotranslate.providers.network import SafeHTTP

    client = SafeHTTP(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, content=b"x" * 2048)),
        resolver=lambda host: ["1.1.1.1"],
    )
    with pytest.raises(ProviderError) as error:
        client.post_json("https://example.hf.space/call/predict", {"data": []}, max_bytes=1024)
    assert error.value.code == "uncertain"
    with pytest.raises(ProviderError) as error:
        client.upload(
            "https://example.hf.space/upload",
            filename="a.wav",
            content=b"fake",
            content_type="audio/wav",
        )
    assert error.value.code == "uncertain"
    client.close()

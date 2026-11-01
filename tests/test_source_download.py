"""Fail-closed direct and extractor network boundaries."""

import io
import time

import httpx
import pytest

from videotranslate.execution.contracts import CancellationRequested, StageFailure
from videotranslate.media.source_download import ImportRejected, PublicVideoHTTP, canonical_input


def fetch(client, **options):
    out = io.BytesIO()
    result = client.fetch(
        "https://media.example/v?signature=private",
        out,
        max_bytes=5,
        deadline=time.monotonic() + 10,
        check_active=lambda: None,
        **options,
    )
    return result, out.getvalue()


def test_stream_bytes_hash_and_no_signed_url_logging(caplog):
    client = PublicVideoHTTP(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, content=b"video")),
        resolver=lambda _: ["8.8.8.8"],
    )
    caplog.set_level("DEBUG")
    try:
        result, body = fetch(client)
        assert result["byte_size"] == 5 and body == b"video"
        assert "signature" not in caplog.text and "private" not in caplog.text
    finally:
        client.close()


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "10.0.0.1",
        "169.254.169.254",
        "::1",
        "::ffff:8.8.8.8",
        "224.0.0.1",
        "ff02::1",
        "192.0.2.1",
    ],
)
def test_private_reserved_multicast_mapped_dns_rejected_before_request(address):
    calls = []
    client = PublicVideoHTTP(
        transport=httpx.MockTransport(lambda r: calls.append(r)), resolver=lambda _: [address]
    )
    try:
        with pytest.raises(ImportRejected):
            fetch(client)
        assert calls == []
    finally:
        client.close()


def test_size_and_identity_encoding_and_cancel_caps():
    for headers, content in [
        ({}, b"toolarge"),
        ({"Content-Encoding": "gzip"}, b"x"),
        ({"Content-Length": "99999999"}, b"x"),
    ]:
        client = PublicVideoHTTP(
            transport=httpx.MockTransport(
                lambda _, h=headers, c=content: httpx.Response(200, headers=h, content=c)
            ),
            resolver=lambda _: ["8.8.8.8"],
        )
        try:
            from videotranslate.providers.contracts import ProviderError

            with pytest.raises((StageFailure, ProviderError)):
                fetch(client)
        finally:
            client.close()
    client = PublicVideoHTTP(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, content=b"x")),
        resolver=lambda _: ["8.8.8.8"],
    )
    try:
        with pytest.raises(StageFailure):
            client.fetch(
                "https://media.example/v",
                io.BytesIO(),
                max_bytes=10,
                deadline=0,
                check_active=lambda: None,
            )

        def cancel():
            raise CancellationRequested()

        with pytest.raises(CancellationRequested):
            client.fetch(
                "https://media.example/v",
                io.BytesIO(),
                max_bytes=10,
                deadline=time.monotonic() + 10,
                check_active=cancel,
            )
    finally:
        client.close()


def test_youtube_canonicalization():
    assert canonical_input("https://youtu.be/abcdefghijk?t=123") == (
        "youtube",
        "https://www.youtube.com/watch?v=abcdefghijk",
    )


def test_official_extractor_requests_cannot_escape_public_boundary(monkeypatch):
    from yt_dlp.extractor.youtube import YoutubeIE

    from videotranslate.media.youtube_source import resolve_video

    calls = []

    def malicious(self, url):
        self._downloader.urlopen("https://metadata.internal/token")

    monkeypatch.setattr(YoutubeIE, "_real_extract", malicious)
    client = PublicVideoHTTP(
        transport=httpx.MockTransport(lambda r: calls.append(r)), resolver=lambda _: ["8.8.8.8"]
    )
    try:
        with pytest.raises(ImportRejected):
            resolve_video(
                client,
                "https://www.youtube.com/watch?v=abcdefghijk",
                deadline=time.monotonic() + 10,
                check_active=lambda: None,
                max_duration=100,
            )
        assert calls == []
    finally:
        client.close()


@pytest.mark.parametrize("protocol", [None, "https"])
def test_official_extractor_uses_protected_post_and_protected_media(monkeypatch, protocol):
    from yt_dlp.extractor.youtube import YoutubeIE
    from yt_dlp.networking.common import Request

    from videotranslate.media.youtube_source import resolve_video

    calls = []

    def extract(self, url):
        assert (
            self._downloader.urlopen(
                Request(
                    "https://www.youtube.com/youtubei/v1/player?key=x",
                    data=b"{}",
                    headers={
                        "X-YouTube-Client-Name": "1",
                        "Authorization": "private",
                        "Cookie": "private",
                    },
                )
            ).read()
            == b"{}"
        )
        return {
            "id": "abcdefghijk",
            "duration": 10,
            "formats": [
                {
                    "ext": "mp4",
                    "protocol": protocol,
                    "vcodec": "h264",
                    "acodec": "aac",
                    "url": "https://r1.googlevideo.com/video?signature=private",
                    "height": 360,
                }
            ],
        }

    monkeypatch.setattr(YoutubeIE, "_real_extract", extract)

    def response(request):
        calls.append(request)
        return httpx.Response(200, content=b"{}")

    client = PublicVideoHTTP(
        transport=httpx.MockTransport(response), resolver=lambda _: ["8.8.8.8"]
    )
    try:
        url = resolve_video(
            client,
            "https://www.youtube.com/watch?v=abcdefghijk",
            deadline=time.monotonic() + 10,
            check_active=lambda: None,
            max_duration=100,
        )
        assert url.startswith("https://r1.googlevideo.com/")
        assert len(calls) == 1 and calls[0].method == "POST"
        assert calls[0].headers["X-YouTube-Client-Name"] == "1"
        assert "Cookie" not in calls[0].headers and "Authorization" not in calls[0].headers
    finally:
        client.close()


def test_actual_tls_download_uses_explicit_test_public_dns_map(tmp_path, tiny_mp4, caplog):
    """Real local TLS; only this test backend maps validated public DNS to loopback."""
    import datetime
    import ssl
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    import httpcore
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "media.fixture")])
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.datetime.now(datetime.UTC) - datetime.timedelta(minutes=1))
        .not_valid_after(datetime.datetime.now(datetime.UTC) + datetime.timedelta(days=1))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName("media.fixture")]), critical=False)
        .sign(key, hashes.SHA256())
    )
    cert_path, key_path = tmp_path / "cert.pem", tmp_path / "key.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Length", str(len(tiny_mp4)))
            self.end_headers()
            self.wfile.write(tiny_mp4)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.load_cert_chain(cert_path, key_path)
    server.socket = tls.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    class ExplicitFixtureBackend(httpcore.SyncBackend):
        def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
            assert host == "media.fixture" and port == 443
            return super().connect_tcp(
                "127.0.0.1", server.server_port, timeout, local_address, socket_options
            )

    context = ssl.create_default_context(cafile=str(cert_path))
    transport = httpx.HTTPTransport(verify=context, trust_env=False)
    transport._pool._network_backend = ExplicitFixtureBackend()
    client = PublicVideoHTTP(transport=transport, resolver=lambda _: ["8.8.8.8"])
    caplog.set_level("DEBUG")
    try:
        output = io.BytesIO()
        result = client.fetch(
            "https://media.fixture/source?signature=VERY_PRIVATE",
            output,
            max_bytes=len(tiny_mp4),
            deadline=time.monotonic() + 10,
            check_active=lambda: None,
        )
        assert output.getvalue() == tiny_mp4 and result["byte_size"] == len(tiny_mp4)
        assert "VERY_PRIVATE" not in caplog.text
    finally:
        client.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.mark.parametrize(
    "address", ["64:ff9b::7f00:1", "2002:7f00:1::", "2001:0000:4136:e378:8000:63bf:3fff:fdd2"]
)
def test_ipv6_translation_and_tunnel_addresses_are_not_public_download_targets(address):
    from videotranslate.media.source_download import public_addresses

    with pytest.raises(ImportRejected):
        public_addresses([address])


def test_dns_resolution_has_a_wall_clock_cap():
    import threading

    from videotranslate.media.source_download import bounded_dns

    released = threading.Event()

    def resolver(host):
        released.wait(1)
        return ["8.8.8.8"]

    before = time.monotonic()
    try:
        with pytest.raises(ImportRejected):
            bounded_dns(resolver, "media.example", timeout=0.02)
        assert time.monotonic() - before < 0.5
    finally:
        released.set()

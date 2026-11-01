"""Public HTTPS media transport. Every hop validates and pins public DNS.

Uses SafeHTTP's verified TLS/pinned connection backend, bypassing Client's
URL-bearing request log. No cookies, proxy environment or caller headers.
"""

import hashlib
import io
import re
import threading
import time
from contextlib import closing
from ipaddress import ip_address
from urllib.parse import parse_qs, urljoin, urlsplit

import httpx

from ..execution.contracts import FailureCode, StageFailure
from ..providers.network import SafeHTTP, require_identity_response, resolve_public


class ImportRejected(ValueError):
    def __init__(self):
        super().__init__("Video link unavailable; upload the source file")


def validate_link(url):
    try:
        if not isinstance(url, str) or not 1 <= len(url) <= 8192:
            raise ValueError()
        if any(ord(c) <= 32 or ord(c) == 127 for c in url) or "\\" in url:
            raise ValueError()
        p = urlsplit(url)
        host = p.hostname or ""
        if (
            p.scheme != "https"
            or not host
            or p.username is not None
            or p.password is not None
            or p.port not in (None, 443)
            or p.fragment
            or not re.fullmatch(r"[a-zA-Z0-9.-]+", host)
            or host.endswith(".")
            or host == "localhost"
            or host.endswith((".localhost", ".local", ".internal"))
        ):
            raise ValueError()
        try:
            ip_address(host)
        except ValueError:
            pass
        else:
            raise ValueError()
        return url
    except (ValueError, TypeError):
        raise ImportRejected() from None


def canonical_input(url):
    validate_link(url)
    p = urlsplit(url)
    host = p.hostname.lower()
    youtube = {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"}
    if host not in youtube:
        if "youtube.com" in host or host.endswith(".youtu.be"):
            raise ImportRejected()
        return "direct", url
    video_id = None
    if host == "youtu.be":
        video_id = p.path.lstrip("/")
    elif p.path == "/watch":
        values = parse_qs(p.query).get("v", [])
        video_id = values[0] if len(values) == 1 else None
    elif p.path.startswith(("/shorts/", "/embed/")):
        video_id = p.path.split("/")[-1]
    if not isinstance(video_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
        raise ImportRejected()
    return "youtube", "https://www.youtube.com/watch?v=" + video_id


_DNS_SLOTS = threading.BoundedSemaphore(4)


def bounded_dns(resolver, host, *, timeout=5):
    """Bound resolver waiting without an unbounded thread/queue on stuck DNS."""
    if not _DNS_SLOTS.acquire(blocking=False):
        raise ImportRejected()
    ready, result = threading.Event(), {}

    def resolve():
        try:
            result["addresses"] = resolver(host)
        except Exception:
            result["failed"] = True
        finally:
            _DNS_SLOTS.release()
            ready.set()

    threading.Thread(target=resolve, daemon=True).start()
    if not ready.wait(timeout) or result.get("failed"):
        raise ImportRejected()
    return public_addresses(result["addresses"])


def public_addresses(addresses):
    try:
        if not addresses:
            raise ValueError()
        for value in addresses:
            addr = ip_address(value)
            if (
                not addr.is_global
                or addr.is_multicast
                or addr.is_reserved
                or addr.is_loopback
                or addr.is_link_local
                or addr.is_unspecified
                or getattr(addr, "ipv4_mapped", None) is not None
            ):
                raise ValueError()
        return addresses
    except ValueError:
        raise ImportRejected() from None


def youtube_host(url):
    host = urlsplit(validate_link(url)).hostname.lower()
    if not any(
        host == root or host.endswith("." + root)
        for root in (
            "youtube.com",
            "googlevideo.com",
            "ytimg.com",
            "youtubei.googleapis.com",
        )
    ):
        raise ImportRejected()


class PublicVideoHTTP(SafeHTTP):
    def __init__(self, *, resolver=None, transport=None, proxy_url=None, use_doh=False):
        if resolver is None and use_doh:
            from ..providers.network import resolve_doh

            def resolver(host):
                return resolve_doh(host, proxy_url)

        base = resolver or resolve_public
        super().__init__(
            resolver=lambda host: bounded_dns(base, host),
            transport=transport,
            proxy_url=proxy_url,
        )

    def fetch(
        self,
        url,
        output,
        *,
        max_bytes,
        deadline,
        check_active,
        youtube=False,
        method="GET",
        data=None,
        metadata=False,
        extractor_headers=None,
    ):
        if method not in {"GET", "POST"} or (method == "POST" and not metadata):
            raise ImportRejected()
        if data is not None and (not isinstance(data, bytes) or len(data) > 1024 * 1024):
            raise ImportRejected()
        for _ in range(4):
            check_active()
            if time.monotonic() >= deadline:
                raise StageFailure(FailureCode.MEDIA_LIMIT)
            validate_link(url)
            if youtube:
                youtube_host(url)
            self.resolver(urlsplit(url).hostname)
            headers = {"Accept-Encoding": "identity", "User-Agent": "VideoTranslate/0.1"}
            if youtube and metadata:
                allowed = {
                    "user-agent",
                    "content-type",
                    "origin",
                    "referer",
                    "x-youtube-client-name",
                    "x-youtube-client-version",
                    "x-goog-visitor-id",
                    "x-youtube-bootstrap-logged-in",
                }
                for name, value in (extractor_headers or {}).items():
                    if name.lower() in allowed and isinstance(value, str) and len(value) <= 2048:
                        if any(ord(c) < 32 or ord(c) == 127 for c in value):
                            raise ImportRejected()
                        headers[name] = value
            if data is not None:
                headers["Content-Type"] = "application/json"
            # handle_request avoids httpx.Client's INFO log containing signed URLs.
            request = httpx.Request(
                method,
                url,
                headers=headers,
                content=data,
                extensions={"timeout": dict(connect=5.0, read=5.0, write=5.0, pool=5.0)},
            )
            try:
                with closing(self.client._transport.handle_request(request)) as response:
                    if response.status_code in {301, 302, 303, 307, 308}:
                        if method != "GET" or not response.headers.get("location"):
                            raise ImportRejected()
                        url = urljoin(url, response.headers["location"])
                        continue
                    if response.status_code >= 400:
                        raise ImportRejected()
                    require_identity_response(response)
                    length = response.headers.get("content-length")
                    if length and (not length.isdecimal() or int(length) > max_bytes):
                        raise StageFailure(FailureCode.MEDIA_LIMIT)
                    size, digest = 0, hashlib.sha256()
                    for chunk in response.stream:
                        check_active()
                        size += len(chunk)
                        if size > max_bytes or time.monotonic() >= deadline:
                            raise StageFailure(FailureCode.MEDIA_LIMIT)
                        digest.update(chunk)
                        output.write(chunk)
                    if not size:
                        raise ImportRejected()
                    return dict(byte_size=size, sha256=digest.hexdigest())
            except httpx.RequestError:
                raise ImportRejected() from None
        raise ImportRejected()

    def metadata(self, request, *, deadline, check_active):
        from yt_dlp.networking.common import Response

        url = request if isinstance(request, str) else request.url
        method = "GET" if isinstance(request, str) else request.method
        data = None if isinstance(request, str) else request.data
        out = io.BytesIO()
        self.fetch(
            url,
            out,
            max_bytes=4 * 1024 * 1024,
            deadline=deadline,
            check_active=check_active,
            youtube=True,
            method=method,
            data=data,
            metadata=True,
            extractor_headers={} if isinstance(request, str) else request.headers,
        )
        out.seek(0)
        return Response(out, url, {"Content-Type": "application/octet-stream"}, status=200)


def make_http(settings):
    return PublicVideoHTTP(
        proxy_url=settings.provider_proxy_url.get_secret_value() or None,
        use_doh=settings.provider_dns_over_https,
    )

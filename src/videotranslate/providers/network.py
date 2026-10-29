"""Validation primitives for provider hosts; callers must also pin DNS during transport."""

from ipaddress import ip_address
from urllib.parse import urlsplit

from .contracts import ProviderError


def validate_url(url: str, *, allowed_hosts: set[str] | None = None) -> str:
    try:
        if any(ord(char) < 32 or ord(char) == 127 for char in url):
            raise ValueError()
        parsed = urlsplit(url)
        host = parsed.hostname or ""
        trusted = (
            host in {"huggingface.co", "router.huggingface.co", "api-inference.huggingface.co"}
            or host.endswith(".hf.space")
            or host in (allowed_hosts or set())
        )
        if (
            parsed.scheme != "https"
            or not trusted
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.port not in (None, 443)
        ):
            raise ValueError()
        try:
            ip_address(host)
        except ValueError:
            pass
        else:
            raise ValueError()
    except ValueError:
        raise ValueError("Invalid provider endpoint") from None
    return url


def validate_public_addresses(addresses: list[str]) -> None:
    if not addresses:
        raise ValueError("Provider host has no public address")
    try:
        if not all(ip_address(address).is_global for address in addresses):
            raise ValueError()
    except ValueError:
        raise ValueError("Provider host has a non-public address") from None


def resolve_public(host: str) -> list[str]:
    import socket

    try:
        addresses = list(
            {item[4][0] for item in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)}
        )
    except OSError:
        raise ProviderError("network") from None
    validate_public_addresses(addresses)
    return addresses


def status_error(status):
    if status in (401, 403):
        return ProviderError("auth")
    if status == 429:
        return ProviderError("quota")
    if status in (400, 404, 405, 422):
        return ProviderError("configuration")
    return ProviderError("network")


class SafeHTTP:
    """Bounded GETs with validated redirects and pinned public DNS for the real transport."""

    def __init__(
        self, *, allowed_hosts=None, transport=None, resolver=None, proxy_url=None, use_doh=False
    ):
        import httpcore
        import httpx

        self.allowed_hosts = allowed_hosts or set()
        if use_doh and not proxy_url:
            raise ValueError("Trusted DNS requires an administrator proxy")
        if resolver is not None:
            self.resolver = resolver
        elif use_doh:
            self.resolver = lambda host: resolve_doh(host, proxy_url)
        else:
            self.resolver = resolve_public
        if transport is None:
            resolver_fn = self.resolver

            class PinnedBackend(httpcore.SyncBackend):
                def connect_tcp(
                    self, host, port, timeout=None, local_address=None, socket_options=None
                ):
                    addresses = resolver_fn(host)
                    validate_public_addresses(addresses)
                    if proxy_url:
                        from httpcore._backends.sync import SyncStream

                        if port != 443:
                            raise ValueError("Invalid provider port")
                        return SyncStream(
                            open_proxy_tunnel(proxy_url, addresses[0], port, timeout or 5)
                        )
                    return super().connect_tcp(
                        addresses[0], port, timeout, local_address, socket_options
                    )

            transport = httpx.HTTPTransport(trust_env=False, retries=0)
            transport._pool._network_backend = PinnedBackend()
        self.client = httpx.Client(
            transport=transport,
            trust_env=False,
            follow_redirects=False,
            timeout=httpx.Timeout(15.0, connect=5.0),
        )

    def close(self):
        self.client.close()

    def get(self, url, *, headers=None, max_bytes=1024 * 1024):
        import httpx

        try:
            return self._get(url, headers=headers, max_bytes=max_bytes)
        except httpx.RequestError:
            raise ProviderError("network") from None

    def _get(self, url, *, headers=None, max_bytes=1024 * 1024):
        from urllib.parse import urljoin, urlsplit

        current_headers = dict(headers or {})
        for _ in range(4):
            validate_url(url, allowed_hosts=self.allowed_hosts)
            validate_public_addresses(self.resolver(urlsplit(url).hostname))
            with self.client.stream("GET", url, headers=current_headers) as response:
                if response.status_code in {301, 302, 303, 307, 308}:
                    location = response.headers.get("location")
                    if not location:
                        raise ValueError("Provider redirect missing destination")
                    next_url = urljoin(url, location)
                    validate_url(next_url, allowed_hosts=self.allowed_hosts)
                    if urlsplit(url).netloc.lower() != urlsplit(next_url).netloc.lower():
                        current_headers = {
                            key: value
                            for key, value in current_headers.items()
                            if key.lower() != "authorization"
                        }
                    url = next_url
                    continue
                if response.status_code >= 400:
                    raise status_error(response.status_code)
                result = bytearray()
                for chunk in response.iter_bytes():
                    result.extend(chunk)
                    if len(result) > max_bytes:
                        raise ValueError("Provider response too large")
                return bytes(result)
        raise ValueError("Too many provider redirects")

    def post_json(
        self, url, body, *, headers=None, max_bytes=1024 * 1024, max_request_bytes=1024 * 1024
    ):
        """Single submission; an interrupted POST has an uncertain remote outcome."""
        import json
        from urllib.parse import urlsplit

        import httpx

        validate_url(url, allowed_hosts=self.allowed_hosts)
        validate_public_addresses(self.resolver(urlsplit(url).hostname))
        encoded = json.dumps(body, ensure_ascii=False, allow_nan=False).encode()
        if not 1 <= max_request_bytes <= 64 * 1024 * 1024 or len(encoded) > max_request_bytes:
            raise ValueError("Provider request too large")
        request_headers = {**(headers or {}), "Content-Type": "application/json"}
        try:
            with self.client.stream(
                "POST", url, headers=request_headers, content=encoded
            ) as response:
                if response.status_code >= 300:
                    raise status_error(response.status_code)
                result = bytearray()
                for chunk in response.iter_bytes():
                    result.extend(chunk)
                    if len(result) > max_bytes:
                        raise ValueError("Provider response too large")
                return bytes(result)
        except httpx.RequestError:
            raise ProviderError("uncertain") from None

    def upload(self, url, *, filename, content, content_type, headers=None):
        """Upload caller-owned bounded bytes once; returned paths remain opaque."""
        import json
        import re
        from urllib.parse import urlsplit

        import httpx

        validate_url(url, allowed_hosts=self.allowed_hosts)
        validate_public_addresses(self.resolver(urlsplit(url).hostname))
        if (
            not re.fullmatch(r"[A-Za-z0-9_.-]{1,200}", filename)
            or filename in {".", ".."}
            or not isinstance(content, bytes)
            or not content
            or len(content) > 64 * 1024 * 1024
            or content_type
            not in {
                "audio/wav",
                "audio/mpeg",
                "audio/flac",
                "audio/ogg",
                "application/octet-stream",
            }
        ):
            raise ValueError("Invalid upload")
        try:
            with self.client.stream(
                "POST", url, headers=headers, files={"files": (filename, content, content_type)}
            ) as response:
                if response.status_code >= 300:
                    raise status_error(response.status_code)
                data = bytearray()
                for chunk in response.iter_bytes():
                    data.extend(chunk)
                    if len(data) > 1024 * 1024:
                        raise ValueError("Provider response too large")
            result = json.loads(data)
            if (
                not isinstance(result, list)
                or len(result) != 1
                or not isinstance(result[0], str)
                or not result[0]
                or result[0].lower().startswith(("file:", "http:", "https:"))
            ):
                raise ValueError("Invalid provider upload response")
            return result
        except httpx.RequestError:
            raise ProviderError("uncertain") from None

    def download(self, url, *, max_bytes=64 * 1024 * 1024, headers=None):
        import os
        import tempfile
        from pathlib import Path

        data = self.get(url, max_bytes=max_bytes, headers=headers)
        fd, path = tempfile.mkstemp(prefix="videotranslate-provider-")
        try:
            with os.fdopen(fd, "wb") as output:
                output.write(data)
            return Path(path)
        except Exception:
            os.unlink(path)
            raise

    def get_sse(self, url, *, headers=None, max_bytes=1024 * 1024, timeout_seconds=30):
        """Read through a terminal SSE event; return partial data on read timeout."""
        import time
        from urllib.parse import urljoin, urlsplit

        import httpx

        deadline = time.monotonic() + timeout_seconds
        current_headers = dict(headers or {})
        for _ in range(4):
            validate_url(url, allowed_hosts=self.allowed_hosts)
            validate_public_addresses(self.resolver(urlsplit(url).hostname))
            data = bytearray()
            try:
                with self.client.stream("GET", url, headers=current_headers) as response:
                    if response.status_code in {301, 302, 303, 307, 308}:
                        location = response.headers.get("location")
                        if not location:
                            raise ValueError("Provider redirect missing destination")
                        next_url = urljoin(url, location)
                        validate_url(next_url, allowed_hosts=self.allowed_hosts)
                        if urlsplit(url).netloc.lower() != urlsplit(next_url).netloc.lower():
                            current_headers = {
                                k: v
                                for k, v in current_headers.items()
                                if k.lower() != "authorization"
                            }
                        url = next_url
                        continue
                    if response.status_code >= 400:
                        raise status_error(response.status_code)
                    for chunk in response.iter_bytes():
                        data.extend(chunk)
                        if len(data) > max_bytes:
                            raise ValueError("Provider event stream too large")
                        normalized = bytes(data).replace(b"\r\n", b"\n")
                        blocks = normalized.split(b"\n\n")[:-1]
                        if any(
                            any(
                                line.strip() in (b"event: complete", b"event: error")
                                for line in block.splitlines()
                            )
                            for block in blocks
                        ):
                            return bytes(data)
                        if time.monotonic() >= deadline:
                            return bytes(data)
                    return bytes(data)
            except httpx.ReadTimeout:
                return bytes(data)
            except httpx.RequestError:
                raise ProviderError("network") from None
        raise ValueError("Too many provider redirects")


def open_proxy_tunnel(proxy_url, target_ip, target_port, timeout):
    """CONNECT to a validated IP through an administrator-selected proxy."""
    import base64
    import socket
    import ssl
    from urllib.parse import unquote, urlsplit

    validate_public_addresses([target_ip])
    try:
        proxy = urlsplit(proxy_url)
        port = proxy.port or (443 if proxy.scheme == "https" else 80)
        if (
            proxy.scheme not in {"http", "https"}
            or not proxy.hostname
            or proxy.path not in {"", "/"}
            or proxy.query
            or proxy.fragment
            or any(ord(c) < 32 for c in proxy_url)
        ):
            raise ValueError()
        if proxy.scheme == "http" and proxy.hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise ValueError()
        connection = socket.create_connection((proxy.hostname, port), timeout=timeout)
        try:
            if proxy.scheme == "https":
                connection = ssl.create_default_context().wrap_socket(
                    connection, server_hostname=proxy.hostname
                )
            target = "[" + target_ip + "]" if ":" in target_ip else target_ip
            authority = f"{target}:{target_port}"
            request = f"CONNECT {authority} HTTP/1.1\r\nHost: {authority}\r\n"
            if proxy.username is not None:
                auth = f"{unquote(proxy.username)}:{unquote(proxy.password or '')}".encode()
                request += "Proxy-Authorization: Basic " + base64.b64encode(auth).decode() + "\r\n"
            connection.sendall((request + "\r\n").encode("ascii"))
            headers = bytearray()
            while b"\r\n\r\n" not in headers:
                part = connection.recv(1)
                if not part or len(headers) + len(part) > 16384:
                    raise ValueError()
                headers.extend(part)
            first = bytes(headers).split(b"\r\n", 1)[0].split()
            if len(first) < 2 or first[1] != b"200":
                raise ValueError()
            return connection
        except Exception:
            connection.close()
            raise
    except Exception:
        raise ProviderError("network") from None


def _doh_query(proxy_url, hostname, record_type):
    """Cloudflare DoH over pinned public CONNECT, with verified resolver TLS."""
    import http.client
    import json
    import ssl
    from urllib.parse import urlencode

    sock = open_proxy_tunnel(proxy_url, "1.1.1.1", 443, 5)
    try:
        tls = ssl.create_default_context().wrap_socket(sock, server_hostname="cloudflare-dns.com")
        try:
            target = "/dns-query?" + urlencode({"name": hostname, "type": record_type})
            tls.sendall(
                f"GET {target} HTTP/1.1\r\nHost: cloudflare-dns.com\r\nAccept: application/dns-json\r\nConnection: close\r\n\r\n".encode(
                    "ascii"
                )
            )
            response = http.client.HTTPResponse(tls)
            response.begin()
            if response.status != 200:
                raise ValueError()
            content = response.read(262145)
            if len(content) > 262144:
                raise ValueError()
            return json.loads(content)
        finally:
            tls.close()
    except Exception:
        sock.close()
        raise ProviderError("network") from None


def resolve_doh(hostname, proxy_url, *, query=None):
    query = query or _doh_query
    addresses = []
    try:
        for record_type, number in [("A", 1), ("AAAA", 28)]:
            data = query(proxy_url, hostname, record_type)
            if (
                not isinstance(data, dict)
                or data.get("Status") != 0
                or not isinstance(data.get("Answer", []), list)
            ):
                raise ValueError()
            for answer in data.get("Answer", []):
                if isinstance(answer, dict) and answer.get("type") == number:
                    addresses.append(str(ip_address(answer["data"])))
        validate_public_addresses(addresses)
        return list(dict.fromkeys(addresses))
    except (KeyError, TypeError, ValueError):
        raise ProviderError("network") from None

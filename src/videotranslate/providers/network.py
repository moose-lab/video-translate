"""Validation primitives for provider hosts; callers must also pin DNS during transport."""

from ipaddress import ip_address
from urllib.parse import urlsplit


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

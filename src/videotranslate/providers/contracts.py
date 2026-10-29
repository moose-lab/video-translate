"""Typed remote contracts; capability declarations are not inference proof."""

from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass(frozen=True)
class ProviderCapabilities:
    """language_support is the default for languages outside the explicit lists."""

    language_support: Literal["supported", "unsupported", "unknown"]
    resumable: bool
    cancel_supported: bool
    inference_verified: bool = False
    stage: str = "unknown"
    supported_languages: tuple[str, ...] = ()
    unsupported_languages: tuple[str, ...] = ()
    tested_languages: tuple[str, ...] = ()
    tested_coverage: Literal["unknown"] = "unknown"
    declared: bool = True
    max_duration_seconds: int | None = None
    controls: tuple[str, ...] = ()


@dataclass(frozen=True)
class RemoteResult:
    status: Literal["pending", "succeeded", "failed", "uncertain"]
    payload: dict[str, Any] = field(default_factory=dict)
    remote_id: str | None = None


class ProviderError(ValueError):
    def __init__(
        self,
        code: Literal["auth", "configuration", "quota", "network", "invalid_response", "uncertain"],
    ):
        self.code = code
        super().__init__(
            "Provider submission outcome uncertain"
            if code == "uncertain"
            else "Remote provider operation failed"
        )

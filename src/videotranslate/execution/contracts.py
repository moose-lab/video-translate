"""Bounded public requests and deliberately safe worker failures."""

import re
from dataclasses import dataclass
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class RunCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    stage: str = Field(min_length=1, max_length=40, pattern=r"^[a-z][a-z0-9_]*$")
    target_language: str | None = Field(
        default=None, min_length=1, max_length=40, pattern=r"^[A-Za-z0-9-]+$"
    )
    segment_id: str | None = Field(
        default=None, min_length=1, max_length=36, pattern=r"^[A-Za-z0-9-]+$"
    )
    options: dict = Field(default_factory=dict)


class RunRetry(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    acknowledge_uncertain_submission: bool = False


class FailureCode(StrEnum):
    TRANSIENT = "TRANSIENT"
    CONFIGURATION = "CONFIGURATION"
    AUTHENTICATION = "AUTHENTICATION"
    UNSUPPORTED_LANGUAGE = "UNSUPPORTED_LANGUAGE"
    INVALID_MEDIA = "INVALID_MEDIA"
    MEDIA_LIMIT = "MEDIA_LIMIT"
    SUBMISSION_UNCERTAIN = "SUBMISSION_UNCERTAIN"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    LEASE_EXPIRED = "LEASE_EXPIRED"


class StageFailure(Exception):
    def __init__(self, code: FailureCode, *, retryable: bool = False, review: bool = False):
        self.code = FailureCode(code)
        self.retryable = retryable and self.code in {FailureCode.TRANSIENT}
        self.review = review or self.code == FailureCode.SUBMISSION_UNCERTAIN
        super().__init__(self.code.value)

    def public(self):
        return {"code": self.code.value, "retryable": self.retryable}


class LeaseLost(Exception):
    pass


class CancellationRequested(Exception):
    pass


@dataclass(frozen=True)
class StageResult:
    facts: dict
    prepared_id: str | None = None


def safe_identifier(value: str, max_length: int = 200) -> str:
    if (
        not isinstance(value, str)
        or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:@/-]*", value)
        or len(value) > max_length
        or "://" in value
        or ".." in value
    ):
        raise ValueError("Invalid provider identifier")
    return value


class StagePending(Exception):
    """A real accepted job is still pending; this is not an inference failure."""

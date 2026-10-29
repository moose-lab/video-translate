"""Explicit runtime configuration. Production never falls back to local persistence."""

from ipaddress import ip_address
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="VT_", env_file=".env", extra="ignore", hide_input_in_errors=True, frozen=True
    )
    environment: Literal["development", "test", "production"] = "development"
    database_url: SecretStr
    storage_backend: Literal["local", "s3"]
    local_storage_root: Path = Path("var/media")
    server_secret: SecretStr = SecretStr("development-only-secret-do-not-use-in-production")
    public_origin: str = "http://localhost:8000"
    debug: bool = False
    provider_allowed_hosts: str = ""
    s3_endpoint_url: str = ""
    s3_bucket: str = ""
    s3_region: str = ""
    s3_access_key: SecretStr = SecretStr("")
    s3_secret_key: SecretStr = SecretStr("")
    upload_max_bytes: int = Field(default=512 * 1024 * 1024, ge=1)
    probe_max_bytes: int = Field(default=512 * 1024 * 1024, ge=1)
    probe_max_duration_seconds: int = Field(default=14400, ge=1)
    probe_max_pixels: int = Field(default=33177600, ge=1)
    probe_timeout_seconds: int = Field(default=60, ge=1)
    worker_lease_seconds: int = Field(default=60, ge=3, le=3600)
    worker_heartbeat_seconds: int = Field(default=15, ge=1)
    worker_poll_seconds: int = Field(default=2, ge=1)
    session_ttl_seconds: int = Field(default=7 * 24 * 3600, ge=60)
    login_max_attempts: int = Field(default=5, ge=1, le=100)
    login_window_seconds: int = Field(default=900, ge=1)

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @model_validator(mode="after")
    def validate_runtime(self):
        try:
            url = make_url(self.database_url.get_secret_value())
        except Exception:
            raise ValueError("Invalid database configuration") from None
        if url.get_backend_name() not in {"sqlite", "postgresql"}:
            raise ValueError("Database must be SQLite or PostgreSQL")
        if self.is_production:
            secret = self.server_secret.get_secret_value()
            origin = urlsplit(self.public_origin)
            if url.drivername != "postgresql+psycopg" or not url.database or not url.host:
                raise ValueError("Production requires a PostgreSQL psycopg connection")
            if (
                len(secret) < 32
                or len(set(secret)) < 12
                or "development" in secret.lower()
                or "change" in secret.lower()
            ):
                raise ValueError(
                    "Production requires a random server secret of at least 32 characters"
                )
            if (
                origin.scheme != "https"
                or not origin.hostname
                or origin.path not in {"", "/"}
                or origin.query
                or origin.fragment
                or origin.username
                or origin.password
            ):
                raise ValueError("Production requires a public HTTPS origin without a path")
            host = origin.hostname
            try:
                public_host = ip_address(host).is_global
            except ValueError:
                public_host = "." in host and not host.endswith((".localhost", ".local"))
            if not public_host:
                raise ValueError("Production origin must have a public hostname or IP address")
            if self.debug:
                raise ValueError("Production debug must be disabled")
            if self.storage_backend != "s3":
                raise ValueError("Production requires private S3 storage")
        if self.worker_heartbeat_seconds >= self.worker_lease_seconds:
            raise ValueError("Worker heartbeat must be shorter than lease")
        if self.storage_backend == "s3":
            endpoint = urlsplit(self.s3_endpoint_url)
            if (
                endpoint.scheme != "https"
                or not endpoint.hostname
                or endpoint.username
                or endpoint.password
                or endpoint.query
                or endpoint.fragment
                or not all(
                    [
                        self.s3_bucket.strip(),
                        self.s3_region.strip(),
                        self.s3_access_key.get_secret_value().strip(),
                        self.s3_secret_key.get_secret_value().strip(),
                    ]
                )
            ):
                raise ValueError("S3 requires an HTTPS endpoint, bucket, region and credentials")
        return self

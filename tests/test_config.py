import importlib.util

import pytest
from pydantic import ValidationError


def settings_type():
    assert importlib.util.find_spec("videotranslate.config") is not None, "Settings missing"
    from videotranslate.config import Settings

    return Settings


def production_values():
    return dict(
        environment="production",
        database_url="postgresql+psycopg://user:pw@db/vt",
        storage_backend="s3",
        server_secret="aB9cD2eF5gH8jK3mN6pQ1rS4tU7vW0xY",
        public_origin="https://video.example.com",
        s3_endpoint_url="https://s3.example.com",
        s3_bucket="private-vt",
        s3_region="us-east-1",
        s3_access_key="test-access",
        s3_secret_key="test-secret",
        debug=False,
    )


def test_explicit_development_config(tmp_path):
    settings = settings_type()(
        database_url=f"sqlite:///{tmp_path}/test.db",
        storage_backend="local",
        local_storage_root=tmp_path / "media",
    )
    assert settings.upload_max_bytes == 512 * 1024 * 1024
    assert not settings.is_production


@pytest.mark.parametrize(
    "field,value",
    [
        ("database_url", "sqlite:///local.db"),
        ("storage_backend", "local"),
        ("server_secret", ""),
        ("server_secret", "change-me"),
        ("debug", True),
        ("public_origin", "http://example.com"),
        ("public_origin", "https://example.com/path"),
        ("s3_endpoint_url", ""),
        ("s3_bucket", ""),
        ("s3_region", ""),
        ("s3_access_key", ""),
        ("s3_secret_key", ""),
    ],
)
def test_production_refuses_unsafe_config(field, value):
    data = production_values()
    data[field] = value
    with pytest.raises(ValidationError):
        settings_type()(**data)


def test_production_accepts_complete_private_storage_config():
    assert settings_type()(**production_values()).is_production


def test_database_and_storage_are_explicit():
    with pytest.raises(ValidationError):
        settings_type()()


def test_initial_migration_on_clean_database(tmp_path):
    from pathlib import Path

    from alembic.autogenerate import compare_metadata
    from alembic.config import Config
    from alembic.migration import MigrationContext
    from sqlalchemy import create_engine, inspect

    from alembic import command
    from videotranslate.db import Base
    from videotranslate.models import core  # noqa: F401

    assert Path("alembic.ini").is_file(), "Initial migration configuration missing"
    database = tmp_path / "migrated.db"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database}")
    command.upgrade(config, "head")
    engine = create_engine(f"sqlite:///{database}")
    try:
        assert set(inspect(engine).get_table_names()) == {
            "alembic_version",
            "users",
            "workspaces",
            "memberships",
            "auth_sessions",
            "login_attempts",
            "projects",
            "assets",
            "stage_runs",
            "run_attempts",
            "run_request_keys",
            "input_states",
            "project_events",
            "workspace_credentials",
            "provider_connections",
            "provider_connection_revisions",
            "source_tracks",
            "source_selections",
            "source_states",
            "transcript_revisions",
            "speakers",
            "speaker_revisions",
            "segments",
            "segment_revisions",
            "segment_parents",
            "language_tracks",
            "context_revisions",
            "translation_revisions",
            "translation_states",
            "translation_commands",
            "translation_phases",
            "voice_settings",
            "voice_settings_versions",
            "synthesis_commands",
            "synthesis_lines",
            "natural_outputs",
            "audio_selections",
            "audio_selection_versions",
            "fit_settings_states",
            "fit_settings_versions",
            "fit_plan_commands",
            "fit_plan_lines",
            "fit_plan_results",
            "voice_qc_commands",
            "voice_qc_lines",
            "voice_qc_results",
            "audio_reviews",
            "private_operations",
            "prepared_objects",
            "analysis_media",
            "workflow_intents",
            "workflow_children",
            "reference_requests",
            "voice_references",
            "reference_versions",
            "voice_bindings",
            "voice_binding_versions",
        }
        with engine.connect() as connection:
            assert compare_metadata(MigrationContext.configure(connection), Base.metadata) == []
        command.downgrade(config, "base")
        assert inspect(engine).get_table_names() == ["alembic_version"]
        command.upgrade(config, "head")
    finally:
        engine.dispose()


def test_production_factory_does_not_create_tables_and_uses_secure_cookies(tmp_path, monkeypatch):
    # SQLite stands in only for the factory/cookie unit test, not PostgreSQL integration evidence.
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine

    from videotranslate.app import create_app
    from videotranslate.db import Base
    from videotranslate.storage import LocalStorage

    engine = create_engine(
        f"sqlite:///{tmp_path}/cookie.db", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    monkeypatch.setattr("videotranslate.app.make_engine", lambda settings: engine)
    monkeypatch.setattr("videotranslate.app.make_storage", lambda settings: LocalStorage(tmp_path))

    def refuse_implicit_schema(*args, **kwargs):
        pytest.fail("Production factory attempted to create tables")

    monkeypatch.setattr(Base.metadata, "create_all", refuse_implicit_schema)
    app = create_app(settings_type()(**production_values()))
    with TestClient(app, base_url="https://video.example.com") as client:
        response = client.post(
            "/api/auth/register",
            json={"email": "prod@example.com", "password": "correct-horse-123", "name": "Creator"},
        )
        assert response.status_code == 201
        assert not app.debug
        assert all(
            "Secure" in cookie and "SameSite=lax" in cookie
            for cookie in response.headers.get_list("set-cookie")
        )
    engine.dispose()


@pytest.mark.parametrize(
    "origin", ["https://localhost", "https://127.0.0.1", "https://192.168.0.1", "https://[::1]"]
)
def test_production_origin_must_be_public(origin):
    data = production_values()
    data["public_origin"] = origin
    with pytest.raises(ValidationError):
        settings_type()(**data)


def test_postgresql_migration_compiles_with_deferred_source_asset_foreign_key():
    # Dialect SQL generation only: no PostgreSQL connection is made by this test.
    from io import StringIO

    from alembic.config import Config

    from alembic import command

    output = StringIO()
    config = Config("alembic.ini", output_buffer=output)
    config.set_main_option("sqlalchemy.url", "postgresql+psycopg://unit:unit@localhost/unit")
    command.upgrade(config, "head", sql=True)
    ddl = output.getvalue()
    assert "TIMESTAMP WITH TIME ZONE" in ddl
    assert ddl.index("CREATE TABLE assets") < ddl.index(
        "ALTER TABLE projects ADD CONSTRAINT fk_projects_source_asset"
    )


def test_provider_proxy_is_secret_and_doh_requires_explicit_proxy(tmp_path):
    import pytest
    from pydantic import ValidationError

    from videotranslate.config import Settings

    values = {
        "environment": "test",
        "database_url": f"sqlite:///{tmp_path}/a.db",
        "storage_backend": "local",
    }
    with pytest.raises(ValidationError):
        Settings(**values, provider_dns_over_https=True)
    settings = Settings(
        **values,
        provider_proxy_url="http://user:fake-password@127.0.0.1:7897",
        provider_dns_over_https=True,
    )
    assert "fake-password" not in repr(settings)

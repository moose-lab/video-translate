"""Opt-in isolated PostgreSQL migration and real CPU/reference ownership evidence."""

import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest


def test_postgresql_populated_analysis_upgrade_down_up_and_cas(client_factory, register, tmp_path):
    import psycopg
    from alembic.autogenerate import compare_metadata
    from alembic.config import Config
    from alembic.migration import MigrationContext
    from dubbing_helpers import create_line, guard, make_probed_project, selected
    from psycopg import sql
    from sqlalchemy import create_engine, text
    from sqlalchemy.exc import IntegrityError
    from test_voice_references import published_upload

    from alembic import command
    from videotranslate.db import Base
    from videotranslate.models.analysis import ReferenceVersion
    from videotranslate.models.core import new_id

    admin_url = os.environ.get("VT_TEST_POSTGRES_ADMIN_URL")
    if not admin_url:
        pytest.skip("Opt-in isolated PostgreSQL test server unavailable")
    name = "analysis_4b_" + uuid4().hex
    admin = psycopg.connect(admin_url, autocommit=True)
    admin.execute(sql.SQL("CREATE DATABASE {} OWNER vt_test").format(sql.Identifier(name)))
    url = (admin_url.rsplit("/", 1)[0] + "/" + name).replace(
        "postgresql://", "postgresql+psycopg://"
    )
    engine = create_engine(url)
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", url)
    client = None
    try:
        command.upgrade(config, "0004_dubbing_domain")
        workspace_id = new_id()
        with engine.begin() as db:
            db.execute(
                text(
                    "INSERT INTO workspaces (id,name,created_at) VALUES (:id,'baseline',CURRENT_TIMESTAMP)"
                ),
                {"id": workspace_id},
            )
            db.execute(
                text(
                    "INSERT INTO workspace_credentials (id,workspace_id,kind,revision,ciphertext,updated_at) VALUES (:id,:workspace,'huggingface',4,'isolated-opaque-ciphertext',CURRENT_TIMESTAMP)"
                ),
                {"id": new_id(), "workspace": workspace_id},
            )
        command.upgrade(config, "head")
        with engine.connect() as db:
            assert compare_metadata(MigrationContext.configure(db), Base.metadata) == []
            assert (
                db.execute(
                    text("SELECT ciphertext FROM workspace_credentials WHERE workspace_id=:id"),
                    {"id": workspace_id},
                ).scalar_one()
                == "isolated-opaque-ciphertext"
            )
        fixture = make_probed_project(lambda: client_factory(database_url=url), register, tmp_path)
        client, headers, p = fixture
        selection = selected(fixture)
        line = create_line(fixture, selection)["segment"]
        ref = published_upload(fixture)
        base = f"/api/projects/{p['id']}"
        role = client.post(base + "/speakers", headers=headers, json={"name": "PG role"}).json()
        body = guard(selection, line["transcript_revision"]) | {
            "revision": 0,
            "reference_version_id": ref["id"],
            "expected_speaker_revision": role["revision"],
        }
        barrier = Barrier(2)

        def promote(_):
            barrier.wait()
            return client.put(
                base + "/speakers/" + role["id"] + "/reference", headers=headers, json=body
            ).status_code

        with ThreadPoolExecutor(2) as pool:
            assert sorted(pool.map(promote, range(2))) == [200, 409]
        other = client.post("/api/projects", headers=headers, json={"name": "Neighbor"}).json()
        with pytest.raises(IntegrityError), client.app.state.session_factory.begin() as db:
            original = db.get(ReferenceVersion, ref["id"])
            values = {
                column.name: getattr(original, column.name)
                for column in ReferenceVersion.__table__.columns
                if column.name not in {"id", "created_at", "project_id"}
            }
            db.add(ReferenceVersion(**values, project_id=other["id"]))
            db.flush()
        with engine.connect() as db:
            project_count = db.execute(text("SELECT count(*) FROM projects")).scalar_one()
            asset_count = db.execute(text("SELECT count(*) FROM assets")).scalar_one()
        command.downgrade(config, "0004_dubbing_domain")
        with engine.connect() as db:
            assert db.execute(text("SELECT count(*) FROM projects")).scalar_one() == project_count
            assert db.execute(text("SELECT count(*) FROM assets")).scalar_one() == asset_count
        command.upgrade(config, "head")
        with engine.connect() as db:
            assert compare_metadata(MigrationContext.configure(db), Base.metadata) == []
            assert (
                db.execute(
                    text("SELECT ciphertext FROM workspace_credentials WHERE workspace_id=:id"),
                    {"id": workspace_id},
                ).scalar_one()
                == "isolated-opaque-ciphertext"
            )
    finally:
        if client:
            client.close()
            client.app.state.engine.dispose()
        engine.dispose()
        admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))
        admin.close()

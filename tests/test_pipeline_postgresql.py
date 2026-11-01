"""Actual isolated PostgreSQL concurrency, restart and uncertainty behavior."""

import os
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest


def test_postgres_pipeline_atomic_start_restart_cancel_resume_no_duplicate_call(
    client_factory, register, tmp_path, monkeypatch
):
    import psycopg
    from alembic.config import Config
    from dubbing_helpers import make_probed_project
    from psycopg import sql
    from sqlalchemy import select
    from test_pipeline import endpoint, proceed, start
    from test_translation_operations import drain, install_chat, translation_project

    from alembic import command
    from videotranslate.models.pipeline import PipelineCommand, PipelineWorkflow
    from videotranslate.models.translation import TranslationPhase

    admin_url = os.getenv("VT_TEST_POSTGRES_ADMIN_URL")
    if not admin_url:
        pytest.skip("Isolated PostgreSQL administrator not configured")
    name = "pipeline_runtime_" + uuid4().hex
    admin = psycopg.connect(admin_url, autocommit=True)
    admin.execute(sql.SQL("CREATE DATABASE {} OWNER vt_test").format(sql.Identifier(name)))
    url = (admin_url.rsplit("/", 1)[0] + "/" + name).replace(
        "postgresql://", "postgresql+psycopg://"
    )
    client = None
    try:
        config = Config("alembic.ini")
        config.set_main_option("sqlalchemy.url", url)
        command.upgrade(config, "head")
        fixture = make_probed_project(lambda: client_factory(database_url=url), register, tmp_path)
        f = translation_project.__wrapped__(fixture)
        client, headers, *_ = f
        chat = install_chat(monkeypatch)
        chat.fail = "draft"
        with ThreadPoolExecutor(max_workers=2) as pool:
            started = list(pool.map(lambda _: start(f), range(2)))
        assert started[0]["id"] == started[1]["id"]
        drain(client)
        detail = client.get(endpoint(f) + "/current").json()
        proceed(f, detail)
        drain(client)
        detail = client.get(endpoint(f) + "/current").json()
        assert detail["targets"][0]["issue"] == "SUBMISSION_UNCERTAIN"
        stopped = client.post(
            endpoint(f) + "/" + detail["id"] + "/cancel",
            headers=headers,
            json={"revision": detail["revision"]},
        )
        assert stopped.status_code == 202
        resumed = client.post(
            endpoint(f) + "/" + detail["id"] + "/resume",
            headers=headers,
            json={"revision": stopped.json()["revision"]},
        )
        assert resumed.status_code == 202
        drain(client)
        assert len(chat.calls) == 1
        with client.app.state.session_factory() as db:
            assert len(db.scalars(select(PipelineWorkflow)).all()) == 1
            assert len(db.scalars(select(PipelineCommand)).all()) == 1
            assert len(db.scalars(select(TranslationPhase)).all()) == 1
    finally:
        if client:
            client.app.state.engine.dispose()
        admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))
        admin.close()

"""Actual isolated PostgreSQL source admission and worker recovery."""

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import select


def test_postgres_atomic_source_import_and_recovery(
    client_factory, register, tiny_mp4, monkeypatch
):
    import psycopg
    from alembic.config import Config
    from psycopg import sql
    from test_source_imports import endpoint, install_http

    from alembic import command
    from videotranslate.execution import worker as worker_module
    from videotranslate.execution.contracts import LeaseLost
    from videotranslate.execution.worker import Worker
    from videotranslate.models.core import utcnow
    from videotranslate.models.execution import StageRun
    from videotranslate.models.source_import import SourceImport

    admin_url = os.getenv("VT_TEST_POSTGRES_ADMIN_URL")
    if not admin_url:
        pytest.skip("Isolated PostgreSQL administrator not configured")
    name = "source_import_runtime_" + uuid4().hex
    admin = psycopg.connect(admin_url, autocommit=True)
    admin.execute(sql.SQL("CREATE DATABASE {} OWNER vt_test").format(sql.Identifier(name)))
    url = (admin_url.rsplit("/", 1)[0] + "/" + name).replace(
        "postgresql://", "postgresql+psycopg://"
    )
    client = worker = None
    try:
        cfg = Config("alembic.ini")
        cfg.set_main_option("sqlalchemy.url", url)
        command.upgrade(cfg, "head")
        client = client_factory(database_url=url)
        auth = register(client)
        headers = {"X-CSRF-Token": auth["csrf_token"]}
        row = client.post("/api/projects", json={"name": "Linked"}, headers=headers).json()

        def start(_):
            response = client.post(
                endpoint(row),
                json={"url": "https://media.example/v?token=private", "revision": row["revision"]},
                headers=headers,
            )
            assert response.status_code == 202, response.text
            return response.json()

        with ThreadPoolExecutor(max_workers=2) as pool:
            jobs = list(pool.map(start, range(2)))
        assert jobs[0]["id"] == jobs[1]["id"]
        calls = []

        def get(request):
            calls.append(request)
            return httpx.Response(200, content=tiny_mp4)

        install_http(monkeypatch, get)
        original = worker_module.finish_run

        def lose(*args, **kwargs):
            raise LeaseLost()

        monkeypatch.setattr(worker_module, "finish_run", lose)
        worker = Worker(client.app.state.settings)
        worker.run_once()
        worker.engine.dispose()
        worker = None
        with client.app.state.session_factory.begin() as db:
            run = db.get(StageRun, jobs[0]["run_id"])
            run.lease_expires_at = utcnow() - timedelta(seconds=1)
        monkeypatch.setattr(worker_module, "finish_run", original)
        worker = Worker(client.app.state.settings)
        worker.run_once()
        done = client.get(endpoint(row) + "/" + jobs[0]["id"]).json()
        assert done["status"] == "succeeded", done
        assert len(calls) == 1
        with client.app.state.session_factory() as db:
            assert len(db.scalars(select(SourceImport)).all()) == 1
        assert client.get(f"/api/projects/{row['id']}/assets").json()["total"] == 1
    finally:
        if worker:
            worker.engine.dispose()
        if client:
            client.app.state.engine.dispose()
        admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))
        admin.close()

"""Actual isolated PostgreSQL guarded admission, worker and owner FKs."""

import os
from uuid import uuid4

import pytest


def test_delivery_postgresql_concurrent_admission_and_owned_download(
    client_factory, register, tmp_path
):
    from concurrent.futures import ThreadPoolExecutor

    import psycopg
    from alembic.config import Config
    from dubbing_helpers import make_probed_project
    from psycopg import sql
    from sqlalchemy import select
    from sqlalchemy.exc import IntegrityError
    from test_deliveries import base, body, fit_original
    from test_translation_operations import drain

    from alembic import command
    from videotranslate.models.core import Asset, new_id
    from videotranslate.models.delivery import DeliveryCommand

    admin_url = os.getenv("VT_TEST_POSTGRES_ADMIN_URL")
    if not admin_url:
        pytest.skip("Opt-in isolated PostgreSQL unavailable")
    name = "delivery_runtime_" + uuid4().hex
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
        client, h, _ = fixture
        plan = fit_original(fixture)
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(
                pool.map(
                    lambda _: client.post(
                        base(fixture) + "/deliveries", headers=h, json=body(plan)
                    ),
                    range(2),
                )
            )
        assert [r.status_code for r in responses] == [202, 202], [r.text for r in responses]
        assert responses[0].json()["id"] == responses[1].json()["id"]
        delivery_id = responses[0].json()["id"]
        drain(client)
        detail = client.get(base(fixture) + "/deliveries/" + delivery_id).json()
        assert detail["status"] == "succeeded" and detail["current"], detail
        movie = next(a for a in detail["artifacts"] if a["format"] == "mp4")
        downloaded = client.get(movie["download_url"])
        assert downloaded.status_code == 200 and len(downloaded.content) == movie["byte_size"]
        other = client.post("/api/projects", headers=h, json={"name": "Other owned project"}).json()
        with client.app.state.session_factory.begin() as db:
            actual = db.get(DeliveryCommand, delivery_id)
            foreign = Asset(
                id=new_id(),
                project_id=other["id"],
                workspace_id=actual.workspace_id,
                filename="other.mp4",
                content_type="video/mp4",
                kind="source_video",
                sha256="f" * 64,
                byte_size=1,
                storage_key="owned-fixture/" + new_id(),
            )
            db.add(foreign)
            foreign_id = foreign.id
        with pytest.raises(IntegrityError) as error, client.app.state.session_factory.begin() as db:
            db.get(DeliveryCommand, delivery_id).source_asset_id = foreign_id
        assert error.value.orig.sqlstate == "23503"
        assert error.value.orig.diag.constraint_name == "fk_delivery_source"
        with client.app.state.session_factory() as db:
            assert len(db.scalars(select(DeliveryCommand)).all()) == 1
    finally:
        if client:
            client.app.state.engine.dispose()
        admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))
        admin.close()

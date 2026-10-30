"""Actual isolated PostgreSQL project-lock CAS/capture/publication and composite owner fences."""

import os
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest


@pytest.mark.parametrize("backend", ["sqlite", "postgresql"])
def test_fit_concurrent_cas_duplicate_capture_and_worker_publication(
    client_factory, register, monkeypatch, tmp_path, backend
):
    from dubbing_helpers import make_probed_project, make_track
    from sqlalchemy import MetaData, select, update
    from sqlalchemy.exc import IntegrityError
    from test_fit_plans import endpoint, fit_payload, listen
    from test_fit_settings import defaults
    from test_synthesis_domain import prepare_synthesis
    from test_synthesis_operations import install_clone, queue
    from test_translation_operations import drain

    from videotranslate.db import Base
    from videotranslate.models.execution import ProjectEvent, StageRun
    from videotranslate.models.finishing import (
        FitPlanCommand,
        FitPlanLine,
        FitPlanResult,
        FitSettingsVersion,
    )

    def clone_schema(bind):
        metadata = MetaData()
        for table in Base.metadata.tables.values():
            table.to_metadata(metadata)
        metadata.create_all(bind)

    monkeypatch.setattr(Base.metadata, "create_all", clone_schema)
    admin = None
    if backend == "postgresql":
        import psycopg
        from psycopg import sql

        url = os.environ.get("VT_TEST_POSTGRES_ADMIN_URL")
        if not url:
            pytest.skip("Opt-in isolated PostgreSQL unavailable")
        name = "fit_runtime_" + uuid4().hex
        admin = psycopg.connect(url, autocommit=True)
        admin.execute(sql.SQL("CREATE DATABASE {} OWNER vt_test").format(sql.Identifier(name)))
        url = (url.rsplit("/", 1)[0] + "/" + name).replace("postgresql://", "postgresql+psycopg://")
    else:
        url = f"sqlite:///{tmp_path}/fit.db"
    c = None
    try:
        f = prepare_synthesis(
            make_probed_project(lambda: client_factory(database_url=url), register, tmp_path)
        )
        c, h, p, *_ = f
        base = f"/api/projects/{p['id']}"
        install_clone(monkeypatch, tmp_path)
        queue(f)
        drain(c)
        listen(f)
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(
                pool.map(
                    lambda borrow: c.put(
                        base + "/fit-settings",
                        headers=h,
                        json=dict(revision=0, settings=defaults() | dict(max_borrow_ms=borrow)),
                    ),
                    (1, 2),
                )
            )
        assert sorted(r.status_code for r in responses) == [200, 409]
        with c.app.state.session_factory() as db:
            assert len(db.scalars(select(FitSettingsVersion)).all()) == 1
        payload = fit_payload(f) | dict(settings_revision=1)
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(
                pool.map(lambda _: c.post(endpoint(f), headers=h, json=payload), range(2))
            )
        assert all(r.status_code == 202 for r in responses), [r.text for r in responses]
        assert len({r.json()["id"] for r in responses}) == 1
        assert sorted(r.json()["reused"] for r in responses) == [False, True]
        command_id = responses[0].json()["id"]
        drain(c)
        state = c.get(endpoint(f) + "/" + command_id).json()
        assert state["status"] == "succeeded" and state["render_eligible"] and state["current"], (
            state
        )
        neighbor = c.post("/api/projects", headers=h, json=dict(name="Neighbor")).json()
        ja = make_track(c, h, base, "ja")
        with c.app.state.session_factory() as db:
            line = db.scalar(select(FitPlanLine))
            result = db.scalar(select(FitPlanResult))
            ids = line.id, result.id
            assert len(db.scalars(select(FitPlanCommand)).all()) == 1
            events = db.scalars(
                select(ProjectEvent).where(
                    ProjectEvent.kind.in_(["finishing.plan_queued", "finishing.plan_published"])
                )
            ).all()
            assert len(events) == 2
            cursor = events[0].sequence
            probe_id = db.scalar(select(StageRun.id).where(StageRun.stage == "probe"))
        # Each probe changes one owner/cell column, avoiding uniqueness collisions.
        for model, identity, values in (
            (FitPlanResult, ids[1], dict(run_id=probe_id)),
            (FitPlanLine, ids[0], dict(track_id=ja["id"])),
            (FitPlanLine, ids[0], dict(project_id=neighbor["id"])),
            (FitPlanResult, ids[1], dict(project_id=neighbor["id"])),
            (FitPlanCommand, command_id, dict(project_id=neighbor["id"])),
        ):
            with pytest.raises(IntegrityError) as error, c.app.state.session_factory.begin() as db:
                db.execute(update(model).where(model.id == identity).values(**values))
            assert "foreign key" in str(error.value).lower()
        replay = c.get(base + f"/events?after={cursor}")
        assert replay.status_code == 200
        assert "finishing.plan_published" in replay.text
        assert "Current target" not in replay.text and "storage_key" not in replay.text
        assert c.get(f"/api/projects/{neighbor['id']}/fit-plans/{command_id}").status_code == 404
    finally:
        if c:
            c.app.state.engine.dispose()
        if admin:
            admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))
            admin.close()

"""Natural inference runtime on isolated real PostgreSQL; provider recording only."""

import os
from uuid import uuid4

import pytest
from dubbing_helpers import make_probed_project
from test_synthesis_domain import body, path, prepare_synthesis
from test_synthesis_operations import history, install_clone, queue
from test_translation_operations import drain


def test_synthesis_runtime_and_output_cell_fences_on_real_postgresql(
    client_factory, register, tmp_path, monkeypatch
):
    import psycopg
    from psycopg import sql
    from sqlalchemy import select
    from sqlalchemy.exc import IntegrityError

    from videotranslate.models.core import new_id
    from videotranslate.models.dubbing import LanguageTrack
    from videotranslate.models.synthesis import AudioSelectionVersion, NaturalOutput

    admin_url = os.environ.get("VT_TEST_POSTGRES_ADMIN_URL")
    if not admin_url:
        pytest.skip("Opt-in isolated PostgreSQL unavailable")
    name = "synthesis_runtime_" + uuid4().hex
    admin = psycopg.connect(admin_url, autocommit=True)
    admin.execute(sql.SQL("CREATE DATABASE {} OWNER vt_test").format(sql.Identifier(name)))
    url = (admin_url.rsplit("/", 1)[0] + "/" + name).replace(
        "postgresql://", "postgresql+psycopg://"
    )
    client = None
    try:
        fixture = make_probed_project(lambda: client_factory(database_url=url), register, tmp_path)
        f = prepare_synthesis(fixture)
        client, h, *_ = f
        http = install_clone(monkeypatch, tmp_path)
        queue(f)
        drain(client)
        output = history(f)["outputs"][0]
        assert output["natural_duration_ms"] == 600
        request = body(f, replace_selected=True)
        request["segments"][0]["selection_revision"] = 1
        assert client.post(path(f) + "/synthesize", headers=h, json=request).status_code == 202
        drain(client)
        assert len(http.posts) == 1 and history(f)["selection_revision"] == 2
        sf = client.app.state.session_factory
        with sf() as db:
            selection = db.scalar(
                select(AudioSelectionVersion).order_by(AudioSelectionVersion.revision.desc())
            )
            values = {c.name: getattr(selection, c.name) for c in selection.__table__.columns}
        with sf.begin() as db:
            track = LanguageTrack(
                id=new_id(), project_id=f[2]["id"], workspace_id=values["workspace_id"], tag="ja"
            )
            db.add(track)
            db.flush()
            foreign_track = track.id
        with pytest.raises(IntegrityError), sf.begin() as db:
            db.add(
                AudioSelectionVersion(
                    **(values | {"id": new_id(), "revision": 3, "track_id": foreign_track})
                )
            )
            db.flush()
        with pytest.raises(IntegrityError), sf.begin() as db:
            from sqlalchemy import update

            db.execute(
                update(NaturalOutput)
                .where(NaturalOutput.id == output["id"])
                .values(track_id=foreign_track)
            )
            db.flush()
    finally:
        if client:
            client.close()
            client.app.state.engine.dispose()
        admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))
        admin.close()

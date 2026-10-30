"""Real isolated PostgreSQL locks/FKs with CPU media and recording remote ASR."""

import os
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import uuid4

import pytest
from dubbing_helpers import guard, make_probed_project, make_track
from test_synthesis_domain import body, path, prepare_synthesis
from test_translation_operations import drain
from test_voice_qc_operations import accept_current, enqueue, prepared, qc_body


@pytest.mark.parametrize("backend", ["sqlite", "postgresql"])
def test_voice_qc_runtime_races_and_composite_owner_fences(
    client_factory, register, monkeypatch, tmp_path, backend
):
    import psycopg
    from psycopg import sql
    from sqlalchemy import MetaData, select, update
    from sqlalchemy.exc import IntegrityError

    from videotranslate.db import Base
    from videotranslate.execution.worker import Worker
    from videotranslate.models.core import new_id
    from videotranslate.models.dubbing import LanguageTrack
    from videotranslate.models.voice_qc import AudioReview, VoiceQCLine, VoiceQCResult

    # PostgreSQL AddConstraint DDL mutates use_alter constraints' _create_rule.
    # Fresh metadata prevents this runtime fixture from disabling later SQLite
    # inline ownership FKs in the same pytest process.
    def isolated_schema(bind):
        metadata = MetaData()
        for table in Base.metadata.tables.values():
            table.to_metadata(metadata)
        metadata.create_all(bind)

    monkeypatch.setattr(Base.metadata, "create_all", isolated_schema)
    admin = None
    if backend == "postgresql":
        admin_url = os.environ.get("VT_TEST_POSTGRES_ADMIN_URL")
        if not admin_url:
            pytest.skip("Opt-in isolated PostgreSQL unavailable")
        name = "voice_qc_runtime_" + uuid4().hex
        admin = psycopg.connect(admin_url, autocommit=True)
        admin.execute(sql.SQL("CREATE DATABASE {} OWNER vt_test").format(sql.Identifier(name)))
        url = (admin_url.rsplit("/", 1)[0] + "/" + name).replace(
            "postgresql://", "postgresql+psycopg://"
        )
    else:
        url = f"sqlite:///{tmp_path}/voice-qc-runtime.db"
    c = None
    release = Event()
    try:
        fixture = make_probed_project(lambda: client_factory(database_url=url), register, tmp_path)
        f = prepare_synthesis(fixture)
        c, h, p, s, line, *_ = f
        http = prepared(f, monkeypatch, tmp_path)
        base = f"/api/projects/{p['id']}"
        make_track(c, h, base, "ja")
        ja_path = path(f).replace("zh-Hant", "ja")
        assert (
            c.patch(
                ja_path + f"/segments/{line['id']}",
                headers=h,
                json=guard(s, line["transcript_revision"])
                | {
                    "revision": 0,
                    "expected_source_text_fingerprint": line["source_text_fingerprint"],
                    "text": "別のターゲット",
                    "approved": True,
                },
            ).status_code
            == 200
        )
        assert c.post(ja_path + "/synthesize", headers=h, json=body(f)).status_code == 202
        drain(c)
        first = enqueue(f)
        payload = qc_body(f)
        payload["segments"][0]["output_id"] = c.get(
            ja_path + f"/segments/{line['id']}/audio-history"
        ).json()["selected_output_id"]
        second = c.post(ja_path + "/voice-qc", headers=h, json=payload)
        assert second.status_code == 202, second.text
        entered = Event()

        def hold_remote():
            entered.set()
            assert release.wait(10)

        http.hook = hold_remote
        with ThreadPoolExecutor(max_workers=2) as pool:
            running = pool.submit(Worker(c.app.state.settings).run_once)
            assert entered.wait(5)
            assert Worker(c.app.state.settings).run_once()
            assert len(http.posts) == 1
            release.set()
            assert running.result(timeout=5)
        http.hook = None
        second_line = c.get(ja_path + "/voice-qc/" + second.json()["id"]).json()["lines"][0]
        assert second_line["status"] == "retry_wait"
        assert second_line["next_action"] == "wait_for_recognition"
        from videotranslate.models.core import utcnow
        from videotranslate.models.execution import StageRun

        with c.app.state.session_factory.begin() as db:
            db.get(StageRun, second_line["run_id"]).due_at = utcnow()
        drain(c)
        assert (
            c.get(ja_path + "/voice-qc/" + second.json()["id"]).json()["lines"][0]["status"]
            == "succeeded"
        )
        assert len(http.posts) == 1
        # Two reviewers holding the same revision and evidence serialize to one acceptance.
        from test_voice_qc_operations import history

        output = history(f)["outputs"][0]
        review = guard(s, line["transcript_revision"]) | {
            "revision": 0,
            "translation_revision": 1,
            "expected_source_text_fingerprint": line["source_text_fingerprint"],
            "audio_selection_revision": 1,
            "output_id": output["id"],
            "decision": "accepted",
            "qc_evidence_fingerprint": output["qc_evidence_fingerprint"],
        }
        endpoint = path(f) + f"/segments/{line['id']}/audio-review"
        with ThreadPoolExecutor(max_workers=2) as pool:
            statuses = list(
                pool.map(lambda _: c.put(endpoint, headers=h, json=review).status_code, range(2))
            )
        assert sorted(statuses) == [200, 409]
        assert accept_current(f, revision=1)["ready"]
        sf = c.app.state.session_factory
        with sf.begin() as db:
            records = [
                db.scalar(select(model)) for model in (VoiceQCLine, VoiceQCResult, AudioReview)
            ]
            identities = [row.id for row in records]
            track = LanguageTrack(
                id=new_id(), workspace_id=records[0].workspace_id, project_id=p["id"], tag="fr"
            )
            db.add(track)
            db.flush()
            foreign_track = track.id
        for model, row_id in zip(
            (VoiceQCLine, VoiceQCResult, AudioReview), identities, strict=True
        ):
            # Updating only the track cannot collide with an existing unique run/line ID.
            # A rejection here must enforce the owned composite cell references.
            with pytest.raises(IntegrityError), sf.begin() as db:
                db.execute(update(model).where(model.id == row_id).values(track_id=foreign_track))
        assert c.get(path(f) + "/voice-qc/" + first["id"]).json()["lines"][0]["current"]
    finally:
        release.set()
        if c:
            c.close()
            c.app.state.engine.dispose()
        if admin:
            admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))
            admin.close()

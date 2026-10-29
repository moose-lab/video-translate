"""Immutable edits and independent manual language tracks."""

from dubbing_helpers import create_line, guard, make_track, selected
from sqlalchemy import select


def test_immutable_edits_split_merge_and_manual_missing_line_repair(dubbing_project):
    c, h, p = dubbing_project
    s = selected(dubbing_project)
    a = create_line(dubbing_project, s)
    base = f"/api/projects/{p['id']}"
    g = guard(s, a["transcript_revision"])
    segment = a["segment"]
    patch = c.patch(
        base + f"/segments/{segment['id']}",
        headers=h,
        json=g | dict(revision=1, text="Hello world", end_ms=900),
    )
    assert patch.status_code == 200, patch.text
    history = c.get(base + f"/segments/{segment['id']}/revisions").json()
    assert [r["text"] for r in history["items"]] == ["Hello", "Hello world"]
    split = c.post(
        base + f"/segments/{segment['id']}/split",
        headers=h,
        json=g
        | {
            "revision": 2,
            "parts": [
                {"text": "Hello", "start_ms": 0, "end_ms": 400, "speaker_id": None},
                {"text": "world", "start_ms": 400, "end_ms": 900, "speaker_id": None},
            ],
        },
    )
    assert split.status_code == 201, split.text
    parts = split.json()["segments"]
    assert all(row["parent_segment_ids"] == [segment["id"]] for row in parts)
    assert (
        c.patch(
            base + f"/segments/{segment['id']}", headers=h, json=g | dict(revision=2, text="x")
        ).status_code
        == 404
    )
    merged = c.post(
        base + "/segments/merge",
        headers=h,
        json=g
        | dict(
            segments=[{"id": row["id"], "revision": 1} for row in parts],
            text="Hello world",
            start_ms=0,
            end_ms=900,
            speaker_id=None,
        ),
    )
    assert merged.status_code == 201, merged.text
    assert set(merged.json()["segment"]["parent_segment_ids"]) == {row["id"] for row in parts}
    assert create_line(dubbing_project, s, "missing", a["transcript_revision"], 1000, 1500)


def test_independent_targets_stale_locked_reapproval_and_context_snapshot(dubbing_project):
    c, h, p = dubbing_project
    s = selected(dubbing_project)
    a = create_line(dubbing_project, s)
    sid = a["segment"]["id"]
    base = f"/api/projects/{p['id']}"
    g = guard(s, a["transcript_revision"])
    zh = make_track(
        c, h, base, "zh", mode="Cinematic", summary="supplied context", glossary={"Hi": "嗨"}
    )
    make_track(c, h, base, "ja")
    for tag, text in [("zh", "你好"), ("ja", "こんにちは")]:
        response = c.patch(
            base + f"/language-tracks/{tag}/segments/{sid}",
            headers=h,
            json=g | dict(revision=0, text=text, locked=True, approved=True),
        )
        assert response.status_code == 200, response.text
    edit = c.patch(base + f"/segments/{sid}", headers=h, json=g | dict(revision=1, text="Goodbye"))
    assert edit.status_code == 200, edit.text
    view = c.get(base + "/timeline?target_language=zh").json()
    tr = view["segments"][0]["translation"]
    assert tr["text"] == "你好" and tr["stale"] and tr["locked"]
    approved = c.post(
        base + "/language-tracks/zh/approve",
        headers=h,
        json=g | {"segments": [{"id": sid, "revision": 1}]},
    )
    assert approved.status_code == 200, approved.text
    tr = c.get(base + "/timeline?target_language=zh").json()["segments"][0]["translation"]
    assert not tr["stale"] and tr["approved"] and tr["revision"] == 2
    assert c.get(base + "/timeline?target_language=ja").json()["segments"][0]["translation"][
        "stale"
    ]
    context = c.patch(
        base + "/language-tracks/zh",
        headers=h,
        json={"revision": zh["revision"], "summary": "new supplied context"},
    )
    assert context.status_code == 200, context.text
    hist = c.get(base + f"/language-tracks/zh/segments/{sid}/revisions").json()["items"]
    assert len(hist) == 2 and all(
        row["context_revision_id"] == zh["context_revision_id"] for row in hist
    )
    assert hist[-1]["parent_revision_id"] == hist[0]["id"]


def test_cast_bindings_merge_and_name_only_facets(dubbing_project):
    from videotranslate.models.execution import InputState

    c, h, p = dubbing_project
    s = selected(dubbing_project)
    a = create_line(dubbing_project, s)
    base = f"/api/projects/{p['id']}"
    g = guard(s, a["transcript_revision"])
    speakers = [
        c.post(base + "/speakers", headers=h, json={"name": name}).json() for name in ["A", "B"]
    ]
    edit = c.patch(
        base + f"/segments/{a['segment']['id']}",
        headers=h,
        json=g | {"revision": 1, "speaker_id": speakers[0]["id"]},
    )
    assert edit.status_code == 200, edit.text
    with c.app.state.session_factory() as db:
        before = {x.key: x.fingerprint for x in db.scalars(select(InputState))}
    rename = c.patch(
        base + f"/speakers/{speakers[0]['id']}", headers=h, json={"revision": 1, "name": "Narrator"}
    )
    assert rename.status_code == 200, rename.text
    with c.app.state.session_factory() as db:
        assert before == {x.key: x.fingerprint for x in db.scalars(select(InputState))}
    merged = c.post(
        base + "/speakers/merge",
        headers=h,
        json=g
        | {
            "source_id": speakers[0]["id"],
            "source_revision": 2,
            "target_id": speakers[1]["id"],
            "target_revision": 1,
        },
    )
    assert merged.status_code == 200, merged.text
    view = c.get(base + "/timeline").json()
    assert view["segments"][0]["speaker_id"] == speakers[1]["id"]
    assert (
        c.patch(
            base + f"/segments/{a['segment']['id']}",
            headers=h,
            json=g | {"revision": 3, "speaker_id": speakers[0]["id"]},
        ).status_code
        == 404
    )


def test_meaning_change_invalidates_committed_manual_translation_descendants_only(dubbing_project):
    from videotranslate.execution.inputs import capture_inputs
    from videotranslate.models.core import Project
    from videotranslate.models.execution import StageRun

    c, h, p = dubbing_project
    s = selected(dubbing_project)
    a = create_line(dubbing_project, s)
    b = create_line(dubbing_project, s, "Second", a["transcript_revision"], 600, 1000)
    sid = a["segment"]["id"]
    base = f"/api/projects/{p['id']}"
    g = guard(s, a["transcript_revision"])
    make_track(c, h, base, "zh")
    assert (
        c.patch(
            base + f"/language-tracks/zh/segments/{sid}",
            headers=h,
            json=g | {"revision": 0, "text": "你好", "locked": True},
        ).status_code
        == 200
    )
    with c.app.state.session_factory.begin() as db:
        project = db.get(Project, p["id"])
        for name, keys in [
            ("natural", [f"translation.zh.{sid}"]),
            ("fit", [f"segment.{sid}.timing"]),
            ("other", [f"segment.{b['segment']['id']}.text"]),
        ]:
            db.add(
                StageRun(
                    workspace_id=project.workspace_id,
                    project_id=project.id,
                    stage=name,
                    scope_key=name,
                    options={},
                    input_project_revision=project.revision,
                    dependency_snapshot=capture_inputs(db, project, keys),
                    dependency_fingerprint="a" * 64,
                    request_fingerprint="b" * 64,
                    output_key=f"test.{name}",
                    status="succeeded",
                )
            )
    assert (
        c.patch(
            base + f"/segments/{sid}", headers=h, json=g | {"revision": 1, "end_ms": 550}
        ).status_code
        == 200
    )
    with c.app.state.session_factory() as db:
        assert {
            r.stage: r.is_stale for r in db.scalars(select(StageRun)).all() if r.stage != "probe"
        } == {"natural": False, "fit": True, "other": False}
    assert (
        c.patch(
            base + f"/segments/{sid}", headers=h, json=g | {"revision": 2, "text": "Bye"}
        ).status_code
        == 200
    )
    with c.app.state.session_factory() as db:
        assert db.scalar(select(StageRun).where(StageRun.stage == "natural")).is_stale


def test_language_track_variants_archive_and_noop_preserve_other_keys(dubbing_project):
    c, h, p = dubbing_project
    base = f"/api/projects/{p['id']}"
    assert c.post(base + "/language-tracks", headers=h, json={"tag": "auto"}).status_code == 422
    zh = make_track(c, h, base, "zh-Hant")
    assert zh["tag"] == "zh-Hant"
    make_track(c, h, base, "ja")
    before = c.get(base).json()["revision"]
    assert (
        c.patch(
            base + "/language-tracks/ja", headers=h, json={"revision": 1, "mode": "Fast"}
        ).status_code
        == 200
    )
    assert c.get(base).json()["revision"] == before
    assert (
        c.patch(
            base + "/language-tracks/zh-Hant", headers=h, json={"revision": 1, "archived": True}
        ).status_code
        == 200
    )
    assert c.get(base).json()["target_languages"] == ["en", "ja"]
    assert c.get(base + "/language-tracks/zh-Hant/contexts").json()["total"] == 1


def test_legacy_project_targets_keep_materialized_track_status_coherent(dubbing_project):
    c, h, p = dubbing_project
    base = f"/api/projects/{p['id']}"
    make_track(c, h, base, "zh")
    assert c.patch(base, headers=h, json={"target_languages": ["ja"]}).status_code == 200
    tracks = {row["tag"]: row for row in c.get(base + "/timeline").json()["language_tracks"]}
    assert tracks["zh"]["archived"]
    assert not tracks["ja"]["materialized"]
    assert c.patch(base, headers=h, json={"target_languages": ["zh"]}).status_code == 200
    tracks = {row["tag"]: row for row in c.get(base + "/timeline").json()["language_tracks"]}
    assert not tracks["zh"]["archived"] and tracks["zh"]["revision"] == 3


def test_archiving_segment_invalidates_existing_manual_target_audio(dubbing_project):
    from videotranslate.execution.inputs import capture_inputs
    from videotranslate.models.core import Project
    from videotranslate.models.execution import StageRun

    c, h, p = dubbing_project
    s = selected(dubbing_project)
    a = create_line(dubbing_project, s)
    base = f"/api/projects/{p['id']}"
    sid = a["segment"]["id"]
    g = guard(s, a["transcript_revision"])
    make_track(c, h, base, "zh")
    assert (
        c.patch(
            base + f"/language-tracks/zh/segments/{sid}",
            headers=h,
            json=g | {"revision": 0, "text": "你好"},
        ).status_code
        == 200
    )
    with c.app.state.session_factory.begin() as db:
        project = db.get(Project, p["id"])
        db.add(
            StageRun(
                workspace_id=project.workspace_id,
                project_id=project.id,
                stage="natural",
                scope_key="natural",
                options={},
                input_project_revision=project.revision,
                dependency_snapshot=capture_inputs(db, project, [f"translation.zh.{sid}"]),
                dependency_fingerprint="a" * 64,
                request_fingerprint="b" * 64,
                output_key="test.natural",
                status="succeeded",
            )
        )
    assert (
        c.post(
            base + f"/segments/{sid}/split",
            headers=h,
            json=g
            | {
                "revision": 1,
                "parts": [
                    {"text": "你", "start_ms": 0, "end_ms": 200, "speaker_id": None},
                    {"text": "好", "start_ms": 200, "end_ms": 500, "speaker_id": None},
                ],
            },
        ).status_code
        == 201
    )
    with c.app.state.session_factory() as db:
        assert db.scalar(select(StageRun).where(StageRun.stage == "natural")).is_stale


def test_actual_edit_events_identify_cells_without_dialogue(dubbing_project):
    c, h, p = dubbing_project
    s = selected(dubbing_project)
    a = create_line(dubbing_project, s, text="Private dialogue must stay out of events")
    base = f"/api/projects/{p['id']}"
    events = c.get(base + "/events").json()["items"]
    created = next(row for row in events if row["kind"] == "segment.created")
    assert created["facts"]["segment_id"] == a["segment"]["id"]
    assert "Private dialogue" not in str(events)


def test_split_requires_explicit_role_distribution(dubbing_project):
    c, h, p = dubbing_project
    s = selected(dubbing_project)
    a = create_line(dubbing_project, s)
    response = c.post(
        f"/api/projects/{p['id']}/segments/{a['segment']['id']}/split",
        headers=h,
        json=guard(s, a["transcript_revision"])
        | {
            "revision": 1,
            "parts": [
                {"text": "One", "start_ms": 0, "end_ms": 200},
                {"text": "Two", "start_ms": 200, "end_ms": 500},
            ],
        },
    )
    assert response.status_code == 422


def test_archived_target_requires_explicit_restore_for_configuration_edits(dubbing_project):
    c, h, p = dubbing_project
    base = f"/api/projects/{p['id']}"
    make_track(c, h, base, "zh")
    assert (
        c.patch(
            base + "/language-tracks/zh", headers=h, json={"revision": 1, "archived": True}
        ).status_code
        == 200
    )
    assert (
        c.patch(
            base + "/language-tracks/zh",
            headers=h,
            json={"revision": 2, "summary": "historical edit"},
        ).status_code
        == 404
    )
    assert (
        c.patch(
            base + "/language-tracks/zh", headers=h, json={"revision": 2, "archived": False}
        ).status_code
        == 200
    )

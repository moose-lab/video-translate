"""Caption data is bounded, previewed without writes, and explicitly mapped."""

import pytest
from dubbing_helpers import create_line, guard, make_track, selected


def test_pure_parser_unicode_markup_and_bounds():
    from videotranslate.dubbing.subtitles import parse_subtitles

    cues = parse_subtitles(
        "WEBVTT\n\n00:00.000 --> 00:00.700\n<v 角色><b>你好</b>\nمرحبا e\u0301<script>bad()</script>\n",
        "vtt",
    )
    assert cues[0]["text"] == "你好\nمرحبا e\u0301"
    assert cues[0]["voice_label"] == "角色"
    assert cues[0]["start_ms"] == 0
    with pytest.raises(ValueError):
        parse_subtitles("x" * 262145, "srt")
    assert parse_subtitles("1\n00:00:00,500 --> 00:00:00,100\nx", "srt")[0]["errors"] == [
        "INVALID_TIMING"
    ]


def test_source_import_preview_apply_replay_and_source_guard(dubbing_project):
    c, h, p = dubbing_project
    s = selected(dubbing_project)
    base = f"/api/projects/{p['id']}"
    body = guard(s) | {"format": "srt", "content": "1\n00:00:00,000 --> 00:00:00,500\n你好"}
    preview = c.post(base + "/source/import/preview", headers=h, json=body)
    assert preview.status_code == 200, preview.text
    assert c.get(base + "/timeline").json()["transcript"] is None
    cue = preview.json()["cues"][0]
    apply = body | {
        "digest": preview.json()["digest"],
        "mode": "new_transcript",
        "mapping": [{"cue_id": cue["id"], "speaker_id": None}],
    }
    result = c.post(base + "/source/import/apply", headers=h, json=apply)
    assert result.status_code == 201, result.text
    assert c.post(base + "/source/import/apply", headers=h, json=apply).status_code == 409
    assert c.get(base + "/timeline").json()["segments"][0]["text"] == "你好"


def test_target_import_explicit_mapping_locked_force_and_no_zip(dubbing_project):
    c, h, p = dubbing_project
    s = selected(dubbing_project)
    a = create_line(dubbing_project, s)
    base = f"/api/projects/{p['id']}"
    make_track(c, h, base, "zh")
    sid = a["segment"]["id"]
    g = guard(s, a["transcript_revision"])
    url = base + "/language-tracks/zh"
    response = c.patch(
        url + f"/segments/{sid}", headers=h, json=g | {"revision": 0, "text": "旧", "locked": True}
    )
    assert response.status_code == 200, response.text
    body = g | {"format": "numbered", "content": "1. 新"}
    preview = c.post(url + "/import/preview", headers=h, json=body)
    assert preview.status_code == 200, preview.text
    assert preview.json()["conflicts"]
    mapping = [{"cue_id": preview.json()["cues"][0]["id"], "segment_id": sid, "revision": 1}]
    apply = body | {"digest": preview.json()["digest"], "mapping": mapping}
    assert c.post(url + "/import/apply", headers=h, json=apply).status_code == 409
    result = c.post(url + "/import/apply", headers=h, json=apply | {"force_locked": True})
    assert result.status_code == 200, result.text
    assert (
        c.get(base + "/timeline?target_language=zh").json()["segments"][0]["translation"]["text"]
        == "新"
    )


def test_mixed_vtt_roles_are_ambiguous_not_inferred_as_first_role():
    from videotranslate.dubbing.subtitles import parse_subtitles

    cue = parse_subtitles("WEBVTT\n\n00:00.000 --> 00:00.700\n<v A>Hello</v> <v B>Bye</v>", "vtt")[
        0
    ]
    assert cue["voice_label"] is None
    assert cue["voice_labels"] == ["A", "B"]
    assert "AMBIGUOUS_VOICE_LABEL" in cue["warnings"]


def test_preview_digest_rejects_intervening_source_or_translation_edit(dubbing_project):
    c, h, p = dubbing_project
    s = selected(dubbing_project)
    a = create_line(dubbing_project, s)
    base = f"/api/projects/{p['id']}"
    sid = a["segment"]["id"]
    g = guard(s, a["transcript_revision"])
    make_track(c, h, base, "zh")
    body = g | {"format": "numbered", "content": "1. hello"}
    preview = c.post(base + "/language-tracks/zh/import/preview", headers=h, json=body).json()
    assert (
        c.patch(
            base + f"/segments/{sid}", headers=h, json=g | {"revision": 1, "text": "Changed"}
        ).status_code
        == 200
    )
    apply = body | {
        "digest": preview["digest"],
        "mapping": [{"cue_id": preview["cues"][0]["id"], "segment_id": sid, "revision": 0}],
    }
    assert (
        c.post(base + "/language-tracks/zh/import/apply", headers=h, json=apply).status_code == 409
    )


def test_failed_import_rolls_back_history_pointers_facets_cast_and_events(dubbing_project):
    from sqlalchemy import select

    from videotranslate.models.execution import InputState

    c, h, p = dubbing_project
    s = selected(dubbing_project)
    a = create_line(dubbing_project, s)
    base = f"/api/projects/{p['id']}"
    before = c.get(base + "/events").json()
    with c.app.state.session_factory() as db:
        fingerprints = {row.key: row.fingerprint for row in db.scalars(select(InputState))}
    body = guard(s, a["transcript_revision"]) | {
        "format": "vtt",
        "content": "WEBVTT\n\n00:00.000 --> 00:00.500\n<v A>one\n\n00:00.600 --> 00:01.000\ntwo",
    }
    preview = c.post(base + "/source/import/preview", headers=h, json=body).json()
    mapping = [{"cue_id": cue["id"], "use_voice_label": True} for cue in preview["cues"]]
    response = c.post(
        base + "/source/import/apply",
        headers=h,
        json=body | {"digest": preview["digest"], "mapping": mapping, "mode": "replace_current"},
    )
    assert response.status_code == 422
    assert c.get(base + "/events").json() == before
    assert c.get(base + "/timeline").json()["transcript"]["id"] == a["transcript_revision"]
    assert c.get(base + "/speakers").json()["total"] == 0
    assert c.get(base + "/transcripts").json()["total"] == 1
    with c.app.state.session_factory() as db:
        assert {row.key: row.fingerprint for row in db.scalars(select(InputState))} == fingerprints

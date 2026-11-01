"""Owned HTTP/Worker ASS and burned MP4, recording inference confined to tests."""
# ruff: noqa: F811

import copy
import json
import subprocess

import pytest
from dubbing_helpers import guard
from sqlalchemy import select
from test_deliveries import base, body, prepare_test_media
from test_fit_plans import fit_payload
from test_synthesis_domain import body as synthesis_body  # noqa: F401
from test_synthesis_domain import synthesis_project  # noqa: F401
from test_synthesis_operations import install_clone
from test_translation_operations import drain


def caption_plan(fixture, monkeypatch, tmp_path, text):
    c, h, _, selection, line, *_ = fixture
    response = c.patch(
        base(fixture) + f"/language-tracks/zh-Hant/segments/{line['id']}",
        headers=h,
        json=guard(selection, line["transcript_revision"])
        | dict(
            revision=1,
            expected_source_text_fingerprint=line["source_text_fingerprint"],
            text=text,
            approved=True,
        ),
    )
    assert response.status_code == 200, response.text
    provider = install_clone(monkeypatch, tmp_path)
    payload = synthesis_body(fixture)
    payload["segments"][0]["translation_revision"] = 2
    assert (
        c.post(
            base(fixture) + "/language-tracks/zh-Hant/synthesize", headers=h, json=payload
        ).status_code
        == 202
    )
    drain(c)
    prepare_test_media(fixture, monkeypatch)
    payload = fit_payload(fixture, "incomplete_preview")
    payload["tracks"][0]["segments"][0]["translation_revision"] = 2
    response = c.post(base(fixture) + "/fit-plans", headers=h, json=payload)
    assert response.status_code == 202, response.text
    drain(c)
    return c.get(base(fixture) + "/fit-plans/" + response.json()["id"]).json(), provider


def caption_request(plan):
    return body(plan) | dict(
        default_audio_track="zh-Hant",
        caption_options=dict(
            formats=["srt", "vtt", "ass"],
            burn_in=True,
            track="bilingual",
            target_track="zh-Hant",
            font_profile="auto",
            font_size=42,
            style="outlined",
        ),
    )


def test_http_worker_private_ass_burned_movie_and_durable_font_proof(
    synthesis_project, monkeypatch, tmp_path
):
    from videotranslate.models.analysis import PrivateOperation

    fixture = synthesis_project
    c, h, *_ = fixture
    from videotranslate.dubbing import delivery_subtitles

    select_fonts = delivery_subtitles.select_fonts

    def outside_sql(*args, **kwargs):
        assert c.app.state.engine.pool.checkedout() == 0, "Font discovery retained SQL connection"
        return select_fonts(*args, **kwargs)

    monkeypatch.setattr(delivery_subtitles, "select_fonts", outside_sql)
    text = "你好 · مرحبا · שלום " + r"{\pos(1,1)}\N"
    plan, provider = caption_plan(fixture, monkeypatch, tmp_path, text)
    response = c.post(base(fixture) + "/deliveries", headers=h, json=caption_request(plan))
    assert response.status_code == 202, response.text
    intent = response.json()
    foreign = caption_request(plan)
    foreign["caption_options"]["target_track"] = "ar"
    assert c.post(base(fixture) + "/deliveries", headers=h, json=foreign).status_code == 422
    drain(c)
    detail = c.get(base(fixture) + "/deliveries/" + intent["id"]).json()
    assert detail["status"] == "succeeded" and detail["manifest_valid"], detail
    assert len(provider.posts) == 1
    assert detail["caption_status"]["fonts"] and detail["caption_status"]["cue_manifest_sha256"]
    target = next(a for a in detail["artifacts"] if (a["track"], a["format"]) == ("zh-Hant", "ass"))
    data = c.get(target["download_url"])
    assert data.status_code == 200 and "text/x-ssa" in data.headers["content-type"]
    assert "你好" in data.text and "مرحبا" in data.text and "שלום" in data.text
    assert "{\\pos" not in data.text and "\\\u2060N" in data.text
    assert "{\\fn" in data.text
    main = next(a for a in detail["artifacts"] if (a["track"], a["format"]) == ("all", "mp4"))
    receipt = main["metadata"]["captions"]
    assert receipt["mode"] == "burn_in" and receipt["track"] == "bilingual"
    assert (
        receipt["target_track"] == "zh-Hant"
        and receipt["fonts"] == detail["caption_status"]["fonts"]
    )
    path = tmp_path / "private-burned.mp4"
    path.write_bytes(c.get(main["download_url"]).content)
    subprocess.run(
        ["ffmpeg", "-v", "error", "-xerror", "-i", str(path), "-map", "0", "-f", "null", "-"],
        check=True,
    )
    streams = json.loads(
        subprocess.check_output(
            ["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(path)]
        )
    )["streams"]
    assert len([s for s in streams if s["codec_type"] == "video"]) == 1
    assert sum(s["disposition"]["default"] for s in streams if s["codec_type"] == "audio") == 1
    with c.app.state.session_factory() as db:
        operation = db.scalar(
            select(PrivateOperation).where(PrivateOperation.run_id == intent["run_id"])
        )
        proof = operation.prepared_payload["caption_proof"]
        assert proof["fonts"] == detail["caption_status"]["fonts"]
        assert proof["glyphs_sha256"] and proof["cue_manifest_sha256"]

    # A self-consistent JSON rewrite must not change current cue identities.
    from videotranslate.execution.inputs import fingerprint
    from videotranslate.models.analysis import PreparedObject

    with c.app.state.session_factory.begin() as db:
        operation = db.scalar(
            select(PrivateOperation).where(PrivateOperation.run_id == intent["run_id"])
        )
        payload = copy.deepcopy(operation.prepared_payload)
        entry = next(e for e in payload["phases"]["export"]["outputs"] if e["format"] == "ass")
        entry["metadata"]["cue_ids"] = ["foreign-cue"]
        item = db.get(PreparedObject, entry["object_id"])
        item.metadata_json = dict(item.metadata_json, cue_ids=["foreign-cue"])
        payload["phases"]["export"]["fingerprint"] = fingerprint(
            payload["phases"]["export"]["outputs"]
        )
        operation.prepared_payload = payload
    corrupt = c.get(base(fixture) + "/deliveries/" + intent["id"]).json()
    assert not corrupt["manifest_valid"] and corrupt["artifacts"] == [], corrupt


def test_missing_glyph_fails_before_any_video_render(synthesis_project, monkeypatch, tmp_path):
    from videotranslate.dubbing import delivery_pipeline

    fixture = synthesis_project
    c, h, *_ = fixture
    plan, provider = caption_plan(fixture, monkeypatch, tmp_path, "你好\U0010ffff")

    def forbidden(*args, **kwargs):
        pytest.fail("Missing glyph reached expensive video rendering")

    monkeypatch.setattr(delivery_pipeline, "render", forbidden)
    response = c.post(base(fixture) + "/deliveries", headers=h, json=caption_request(plan))
    assert response.status_code == 202, response.text
    drain(c)
    detail = c.get(base(fixture) + "/deliveries/" + response.json()["id"]).json()
    assert detail["status"] == "needs_review" and detail["artifacts"] == [], detail
    assert detail["error"]["issue"] == "FONT_GLYPHS_MISSING"
    assert detail["error"]["missing"] == ["U+10FFFF"]
    assert len(provider.posts) == 1


def test_explicit_empty_ass_sidecar_keeps_original_only_identity(dubbing_project, monkeypatch):
    from test_deliveries import fit_original

    c, h, _ = dubbing_project
    plan = fit_original(dubbing_project)
    requested = body(plan) | dict(caption_options=dict(formats=["ass"]))
    response = c.post(base(dubbing_project) + "/deliveries", headers=h, json=requested)
    assert response.status_code == 202, response.text
    drain(c)
    detail = c.get(base(dubbing_project) + "/deliveries/" + response.json()["id"]).json()
    assert detail["status"] == "succeeded" and detail["manifest_valid"], detail
    assert [
        (a["track"], a["format"])
        for a in detail["artifacts"]
        if a["format"] in {"srt", "vtt", "ass"}
    ] == [("source", "ass")]
    ass = next(a for a in detail["artifacts"] if a["format"] == "ass")
    assert ass["metadata"]["cue_count"] == 0
    assert "Dialogue:" not in c.get(ass["download_url"]).text


def test_caption_export_retry_preserves_render_mix_and_font_checkpoint(
    synthesis_project, monkeypatch, tmp_path
):
    from videotranslate.dubbing import delivery_pipeline
    from videotranslate.execution.contracts import FailureCode, StageFailure
    from videotranslate.media import delivery_export
    from videotranslate.models.analysis import PrivateOperation

    fixture = synthesis_project
    c, h, *_ = fixture
    plan, provider = caption_plan(fixture, monkeypatch, tmp_path, "你好 مرحبا שלום")
    mux = delivery_export.mux
    monkeypatch.setattr(
        delivery_export,
        "mux",
        lambda *args, **kwargs: (_ for _ in ()).throw(StageFailure(FailureCode.INVALID_MEDIA)),
    )
    response = c.post(base(fixture) + "/deliveries", headers=h, json=caption_request(plan))
    assert response.status_code == 202, response.text
    intent = response.json()
    drain(c)
    failed = c.get(base(fixture) + "/deliveries/" + intent["id"]).json()
    assert failed["status"] == "failed" and failed["artifacts"] == [], failed
    with c.app.state.session_factory() as db:
        operation = db.scalar(
            select(PrivateOperation).where(PrivateOperation.run_id == intent["run_id"])
        )
        prior = copy.deepcopy(operation.prepared_payload)
        generation = operation.generation
        assert set(prior["phases"]) == {"render", "mix"}
        assert prior["caption_proof"]["fonts"]

    def forbidden(*args, **kwargs):
        pytest.fail("Retry recomputed completed render/mix")

    monkeypatch.setattr(delivery_pipeline, "render", forbidden)
    monkeypatch.setattr(delivery_pipeline, "mix_tracks", forbidden)
    monkeypatch.setattr(delivery_export, "mux", mux)
    response = c.post("/api/runs/" + intent["run_id"] + "/retry", headers=h, json={})
    assert response.status_code == 200, response.text
    drain(c)
    detail = c.get(base(fixture) + "/deliveries/" + intent["id"]).json()
    assert detail["status"] == "succeeded" and detail["manifest_valid"], detail
    with c.app.state.session_factory() as db:
        operation = db.scalar(
            select(PrivateOperation).where(PrivateOperation.run_id == intent["run_id"])
        )
        assert operation.generation == generation
        assert operation.prepared_payload["caption_proof"] == prior["caption_proof"]
        for phase in ("render", "mix"):
            assert operation.prepared_payload["phases"][phase] == prior["phases"][phase]
    assert len(provider.posts) == 1

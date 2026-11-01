"""Owned delivery acceptance using tiny real media, no inference providers."""
# ruff: noqa: F811

import json
import subprocess

from dubbing_helpers import guard, selected
from test_translation_operations import drain


def base(f):
    return f"/api/projects/{f[2]['id']}"


def fit_original(f):
    c, h, _ = f
    response = c.post(
        base(f) + "/fit-plans",
        headers=h,
        json=guard(selected(f)) | dict(settings_revision=0, purpose="original_only", tracks=[]),
    )
    assert response.status_code == 202, response.text
    drain(c)
    return c.get(base(f) + "/fit-plans/" + response.json()["id"]).json()


def body(plan):
    return dict(
        fit_plan_id=plan["id"],
        expected_fit_run_id=plan["run_id"],
        purpose=plan["purpose"],
        frame_rate=dict(numerator=25, denominator=1),
        background_gain=1.0,
        voice_gain=1.0,
        include_original_comparison=True,
        default_audio_track="original",
        captions="sidecar",
    )


def test_original_delivery_http_worker_private_mp4(dubbing_project, tmp_path):

    c, h, _ = dubbing_project
    plan = fit_original(dubbing_project)
    response = c.post(base(dubbing_project) + "/deliveries", headers=h, json=body(plan))
    assert response.status_code == 202, response.text
    delivery = response.json()
    drain(c)
    detail = c.get(base(dubbing_project) + "/deliveries/" + delivery["id"])
    assert detail.status_code == 200, detail.text
    result = detail.json()
    assert result["status"] == "succeeded", result
    assert result["current"] is True and result["purpose"] == "original_only"
    artifacts = result["artifacts"]
    assert {a["format"] for a in artifacts} >= {"mp4", "wav"}
    movie = next(a for a in artifacts if a["format"] == "mp4")
    content = c.get(movie["download_url"])
    assert content.status_code == 200
    path = tmp_path / "downloaded.mp4"
    path.write_bytes(content.content)
    info = json.loads(
        subprocess.check_output(
            ["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(path)]
        )
    )
    video = [s for s in info["streams"] if s["codec_type"] == "video"]
    audio = [s for s in info["streams"] if s["codec_type"] == "audio"]
    assert len(video) == len(audio) == 1
    assert video[0]["codec_name"] == "h264" and video[0]["pix_fmt"] == "yuv420p"
    assert audio[0]["codec_name"] == "aac" and audio[0]["disposition"]["default"] == 1
    subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-map", "0", "-f", "null", "-"], check=True
    )
    assert c.get(base(dubbing_project) + "/deliveries").json()["total"] == 1


def prepare_test_media(fixture, monkeypatch):
    """Only labelled recording separation; extraction and storage remain real."""
    from test_analysis_workflow import configure_remote, recording_provider

    c, h, *_ = fixture
    configure_remote(fixture[:3])
    recording_provider(monkeypatch, c)
    response = c.post(base(fixture) + "/runs", headers=h, json={"stage": "extract"})
    assert response.status_code == 201, response.text
    drain(c)
    response = c.post(base(fixture) + "/runs", headers=h, json={"stage": "separate"})
    assert response.status_code == 201, response.text
    drain(c)


from test_synthesis_domain import synthesis_project  # noqa: E402,F401


def test_target_delivery_exports_current_accepted_audio_and_sidecars(
    synthesis_project, monkeypatch, tmp_path
):
    from test_fit_plans import fit_payload, listen
    from test_synthesis_operations import install_clone, queue

    fixture = synthesis_project
    c, h, *_ = fixture
    provider = install_clone(monkeypatch, tmp_path)
    queue(fixture)
    drain(c)
    listen(fixture)
    prepare_test_media(fixture, monkeypatch)
    response = c.post(base(fixture) + "/fit-plans", headers=h, json=fit_payload(fixture))
    assert response.status_code == 202, response.text
    drain(c)
    plan = c.get(base(fixture) + "/fit-plans/" + response.json()["id"]).json()
    requested = body(plan)
    requested["default_audio_track"] = "zh-Hant"
    response = c.post(base(fixture) + "/deliveries", headers=h, json=requested)
    assert response.status_code == 202, response.text
    drain(c)
    result = c.get(base(fixture) + "/deliveries/" + response.json()["id"]).json()
    assert result["status"] == "succeeded", result
    assert len(provider.posts) == 1
    artifacts = result["artifacts"]
    assert {(a["track"], a["format"]) for a in artifacts} >= {
        ("zh-Hant", "mp4"),
        ("zh-Hant", "wav"),
        ("zh-Hant", "srt"),
        ("zh-Hant", "vtt"),
        ("source", "srt"),
        ("source", "vtt"),
    }
    srt = next(a for a in artifacts if a["track"] == "zh-Hant" and a["format"] == "srt")
    assert "這是目標文字。" in c.get(srt["download_url"]).text
    movie = next(a for a in artifacts if a["track"] == "all" and a["format"] == "mp4")
    path = tmp_path / "target-download.mp4"
    path.write_bytes(c.get(movie["download_url"]).content)
    streams = json.loads(
        subprocess.check_output(
            ["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(path)]
        )
    )["streams"]
    audio = [s for s in streams if s["codec_type"] == "audio"]
    assert len(audio) == 2
    assert [s["tags"]["language"] for s in audio] == ["und", "zho"]
    assert [s["disposition"]["default"] for s in audio] == [0, 1]
    subprocess.run(
        ["ffmpeg", "-v", "error", "-xerror", "-i", str(path), "-map", "0", "-f", "null", "-"],
        check=True,
    )


def test_export_failure_retains_cpu_phases_across_gc_and_retry(dubbing_project, monkeypatch):
    from datetime import timedelta

    from sqlalchemy import select

    from videotranslate.execution.contracts import FailureCode, StageFailure
    from videotranslate.execution.prepared import cleanup_orphans
    from videotranslate.media import delivery_export, fit_audio, fit_video
    from videotranslate.models.analysis import PreparedObject, PrivateOperation
    from videotranslate.models.core import utcnow

    c, h, _ = dubbing_project
    plan = fit_original(dubbing_project)
    response = c.post(base(dubbing_project) + "/deliveries", headers=h, json=body(plan))
    assert response.status_code == 202, response.text
    intent = response.json()
    mux = delivery_export.mux
    monkeypatch.setattr(
        delivery_export,
        "mux",
        lambda *a, **kw: (_ for _ in ()).throw(StageFailure(FailureCode.INVALID_MEDIA)),
    )
    drain(c)
    failed = c.get(base(dubbing_project) + "/deliveries/" + intent["id"]).json()
    assert failed["status"] == "failed" and failed["artifacts"] == []
    with c.app.state.session_factory() as db:
        operation = db.scalar(
            select(PrivateOperation).where(PrivateOperation.run_id == intent["run_id"])
        )
        assert operation.phase == "ready" and set(operation.prepared_payload["phases"]) == {
            "render",
            "mix",
        }
        generation = operation.generation
        workspace = operation.workspace_id
        objects = list(operation.prepared_payload["objects"])
    deleted = cleanup_orphans(
        c.app.state.session_factory,
        c.app.state.storage,
        workspace_id=workspace,
        before=utcnow() + timedelta(seconds=1),
    )
    assert deleted == 0, "Current durable CPU intermediates were garbage collected"

    def forbidden(*a, **kw):
        raise AssertionError("A completed render was recomputed")

    monkeypatch.setattr(fit_video, "retime_video", forbidden)
    monkeypatch.setattr(fit_audio, "retime_audio", forbidden)
    monkeypatch.setattr(delivery_export, "mux", mux)
    retry = c.post("/api/runs/" + intent["run_id"] + "/retry", headers=h, json={})
    assert retry.status_code == 200, retry.text
    drain(c)
    result = c.get(base(dubbing_project) + "/deliveries/" + intent["id"]).json()
    assert result["status"] == "succeeded", result
    with c.app.state.session_factory() as db:
        operation = db.scalar(
            select(PrivateOperation).where(PrivateOperation.run_id == intent["run_id"])
        )
        assert operation.generation == generation
        assert all(db.get(PreparedObject, i).state == "published" for i in objects)


def test_prepared_publication_restart_reuses_all_cpu_media(dubbing_project, monkeypatch):
    from dataclasses import replace

    from sqlalchemy import select

    from videotranslate.dubbing import delivery_pipeline
    from videotranslate.execution.registry import STAGES
    from videotranslate.models.analysis import PrivateOperation

    c, h, _ = dubbing_project
    plan = fit_original(dubbing_project)
    response = c.post(base(dubbing_project) + "/deliveries", headers=h, json=body(plan))
    intent = response.json()
    original = STAGES["deliver"]

    def broken(*args):
        raise RuntimeError("recorded publication interruption")

    monkeypatch.setitem(STAGES, "deliver", replace(original, publish=broken))
    drain(c)
    with c.app.state.session_factory() as db:
        operation = db.scalar(
            select(PrivateOperation).where(PrivateOperation.run_id == intent["run_id"])
        )
        assert operation.phase == "prepared"
        key = operation.generation
    monkeypatch.setitem(STAGES, "deliver", original)

    def forbidden(*a, **kw):
        raise AssertionError("Prepared success recomputed CPU media")

    for name in ("render", "mix_tracks", "export"):
        monkeypatch.setattr(delivery_pipeline, name, forbidden)
    retry = c.post("/api/runs/" + intent["run_id"] + "/retry", headers=h, json={})
    assert retry.status_code == 200, retry.text
    drain(c)
    result = c.get(base(dubbing_project) + "/deliveries/" + intent["id"]).json()
    assert result["status"] == "succeeded" and result["manifest_valid"], result
    with c.app.state.session_factory() as db:
        operation = db.scalar(
            select(PrivateOperation).where(PrivateOperation.run_id == intent["run_id"])
        )
        assert operation.generation == key


def test_two_target_audio_tracks_share_one_picture_and_have_independent_downloads(
    synthesis_project, monkeypatch, tmp_path
):
    """Multilingual protocol recording only: no real Japanese inference call."""
    from dubbing_helpers import make_track
    from test_fit_plans import fit_payload, listen
    from test_synthesis_domain import body as synthesis_body
    from test_synthesis_operations import install_clone, queue

    fixture = synthesis_project
    c, h, p, selection, line, *_ = fixture
    provider = install_clone(monkeypatch, tmp_path)
    queue(fixture)
    drain(c)
    listen(fixture)
    make_track(c, h, base(fixture), "ja")
    response = c.patch(
        base(fixture) + f"/language-tracks/ja/segments/{line['id']}",
        headers=h,
        json=guard(selection, line["transcript_revision"])
        | dict(
            revision=0,
            expected_source_text_fingerprint=line["source_text_fingerprint"],
            text="日本語のテスト",
            approved=True,
        ),
    )
    assert response.status_code == 200, response.text
    response = c.post(
        base(fixture) + "/language-tracks/ja/synthesize", headers=h, json=synthesis_body(fixture)
    )
    assert response.status_code == 202, response.text
    drain(c)
    history = c.get(
        base(fixture) + f"/language-tracks/ja/segments/{line['id']}/audio-history"
    ).json()
    output = history["outputs"][0]
    review = guard(selection, line["transcript_revision"]) | dict(
        revision=output["review_revision"],
        translation_revision=1,
        expected_source_text_fingerprint=line["source_text_fingerprint"],
        audio_selection_revision=history["selection_revision"],
        output_id=output["id"],
        qc_evidence_fingerprint=output["qc_evidence_fingerprint"],
        decision="accepted",
    )
    response = c.put(
        base(fixture) + f"/language-tracks/ja/segments/{line['id']}/audio-review",
        headers=h,
        json=review,
    )
    assert response.status_code == 200, response.text
    prepare_test_media(fixture, monkeypatch)
    payload = fit_payload(fixture)
    payload["tracks"].append(
        dict(
            tag="ja",
            segments=[
                dict(
                    id=line["id"],
                    expected_source_revision_id=line["revision_id"],
                    expected_source_text_fingerprint=line["source_text_fingerprint"],
                    translation_revision=1,
                    selection_revision=history["selection_revision"],
                    output_id=output["id"],
                    review_revision=response.json()["review_revision"],
                    qc_evidence_fingerprint=output["qc_evidence_fingerprint"],
                )
            ],
        )
    )
    response = c.post(base(fixture) + "/fit-plans", headers=h, json=payload)
    assert response.status_code == 202, response.text
    drain(c)
    plan = c.get(base(fixture) + "/fit-plans/" + response.json()["id"]).json()
    requested = body(plan)
    requested["default_audio_track"] = "ja"
    response = c.post(base(fixture) + "/deliveries", headers=h, json=requested)
    assert response.status_code == 202, response.text
    drain(c)
    result = c.get(base(fixture) + "/deliveries/" + response.json()["id"]).json()
    assert result["status"] == "succeeded", result
    assert len(provider.posts) == 2
    movie = next(a for a in result["artifacts"] if (a["track"], a["format"]) == ("all", "mp4"))
    path = tmp_path / "two-target.mp4"
    path.write_bytes(c.get(movie["download_url"]).content)
    streams = json.loads(
        subprocess.check_output(
            ["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(path)]
        )
    )["streams"]
    assert len([s for s in streams if s["codec_type"] == "video"]) == 1
    audio = [s for s in streams if s["codec_type"] == "audio"]
    assert len(audio) == 3 and sum(s["disposition"]["default"] for s in audio) == 1
    assert next(s for s in audio if s["disposition"]["default"])["tags"]["language"] == "jpn"
    assert {(a["track"], a["format"]) for a in result["artifacts"]} >= {
        ("zh-Hant", "mp4"),
        ("ja", "mp4"),
        ("zh-Hant", "mp3"),
        ("ja", "mp3"),
    }
    subprocess.run(
        ["ffmpeg", "-v", "error", "-xerror", "-i", str(path), "-map", "0", "-f", "null", "-"],
        check=True,
    )


def test_unaccepted_current_naturals_export_only_as_explicit_incomplete_preview(
    synthesis_project, monkeypatch, tmp_path
):
    from test_fit_plans import fit_payload
    from test_synthesis_operations import install_clone, queue

    fixture = synthesis_project
    c, h, *_ = fixture
    install_clone(monkeypatch, tmp_path)
    queue(fixture)
    drain(c)
    prepare_test_media(fixture, monkeypatch)
    denied = c.post(base(fixture) + "/fit-plans", headers=h, json=fit_payload(fixture))
    assert denied.status_code == 409, denied.text
    response = c.post(
        base(fixture) + "/fit-plans", headers=h, json=fit_payload(fixture, "incomplete_preview")
    )
    assert response.status_code == 202, response.text
    drain(c)
    plan = c.get(base(fixture) + "/fit-plans/" + response.json()["id"]).json()
    assert plan["current"] and not plan["dub_ready"] and plan["lines"][0]["included"]
    requested = body(plan)
    requested["default_audio_track"] = "zh-Hant"
    response = c.post(base(fixture) + "/deliveries", headers=h, json=requested)
    assert response.status_code == 202, response.text
    drain(c)
    detail = c.get(base(fixture) + "/deliveries/" + response.json()["id"]).json()
    assert detail["status"] == "succeeded" and detail["purpose"] == "incomplete_preview", detail
    assert any(a["track"] == "zh-Hant" and a["format"] == "mp4" for a in detail["artifacts"])

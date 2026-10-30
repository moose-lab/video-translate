"""Natural line synthesis contracts; recording providers are test-only."""

import pytest
from dubbing_helpers import create_line, guard, make_track, selected
from test_voice_references import published_upload


@pytest.fixture
def synthesis_project(dubbing_project):
    return prepare_synthesis(dubbing_project)


def prepare_synthesis(dubbing_project):
    c, h, p = dubbing_project
    s = selected(dubbing_project)
    line = create_line(dubbing_project, s, "English source", end_ms=800)["segment"]
    base = f"/api/projects/{p['id']}"
    track = make_track(c, h, base, "zh-Hant")
    ref = published_upload(dubbing_project)
    binding = c.put(
        base + f"/segments/{line['id']}/reference",
        headers=h,
        json=guard(s, line["transcript_revision"])
        | {
            "revision": 0,
            "expected_segment_revision": line["revision"],
            "reference_version_id": ref["id"],
        },
    )
    assert binding.status_code == 200, binding.text
    response = c.patch(
        base + f"/language-tracks/zh-Hant/segments/{line['id']}",
        headers=h,
        json=guard(s, line["transcript_revision"])
        | {
            "revision": 0,
            "expected_source_text_fingerprint": line["source_text_fingerprint"],
            "text": "這是目標文字。",
            "approved": True,
        },
    )
    assert response.status_code == 200, response.text
    configured = c.put(
        "/api/providers/synthesis",
        headers=h,
        json={
            "revision": 0,
            "adapter": "omnivoice",
            "space_id": "k2-fsa/OmniVoice",
            "model": "OmniVoice",
            "credential_ref": None,
        },
    )
    assert configured.status_code == 200, configured.text
    return c, h, p, s, line, track, ref


def path(fixture):
    return f"/api/projects/{fixture[2]['id']}/language-tracks/zh-Hant"


def body(fixture, **extra):
    _, _, _, s, line, _, _ = fixture
    return (
        guard(s, line["transcript_revision"])
        | {
            "segments": [
                {
                    "id": line["id"],
                    "translation_revision": 1,
                    "expected_source_text_fingerprint": line["source_text_fingerprint"],
                    "selection_revision": 0,
                }
            ]
        }
        | extra
    )


def test_owned_current_line_enqueues_one_independent_command_only_run(synthesis_project):
    c, h, *_ = synthesis_project
    response = c.post(
        path(synthesis_project) + "/synthesize", headers=h, json=body(synthesis_project)
    )
    assert response.status_code == 202, response.text
    result = response.json()
    assert len(result["lines"]) == 1
    assert result["lines"][0]["status"] == "queued"
    repeated = c.post(
        path(synthesis_project) + "/synthesize", headers=h, json=body(synthesis_project)
    )
    assert repeated.status_code == 202 and repeated.json()["id"] == result["id"]
    assert (
        c.post(
            f"/api/projects/{synthesis_project[2]['id']}/runs",
            headers=h,
            json={"stage": "synthesize", "target_language": "zh-Hant"},
        ).status_code
        == 422
    )


@pytest.mark.parametrize(
    "change", ["missing", "foreign", "stale_target", "source_proof", "reference"]
)
def test_missing_foreign_or_stale_inputs_cannot_enqueue(synthesis_project, change):
    c, h, p, *_ = synthesis_project
    request = body(synthesis_project)
    if change in {"missing", "foreign"}:
        request["segments"][0]["id"] = "unowned-id"
    elif change == "stale_target":
        request["segments"][0]["translation_revision"] = 0
    elif change == "source_proof":
        request["segments"][0]["expected_source_text_fingerprint"] = "a" * 64
    else:
        r = c.put(
            f"/api/projects/{p['id']}/segments/{synthesis_project[4]['id']}/reference",
            headers=h,
            json=guard(synthesis_project[3], synthesis_project[4]["transcript_revision"])
            | {"revision": 1, "expected_segment_revision": 1, "reference_version_id": None},
        )
        assert r.status_code == 200
    result = c.post(path(synthesis_project) + "/synthesize", headers=h, json=request)
    assert result.status_code in {404, 409, 422}, result.text


def test_voice_controls_have_cas_immutable_history_and_clear_override(synthesis_project):
    c, h, _, s, line, *_ = synthesis_project
    endpoint = path(synthesis_project) + f"/segments/{line['id']}/voice-settings"
    data = guard(s, line["transcript_revision"]) | {
        "revision": 0,
        "controls": {"ns": 16, "sp": 1.1},
    }
    result = c.put(endpoint, headers=h, json=data)
    assert result.status_code == 200, result.text
    assert result.json()["revision"] == 1
    assert c.put(endpoint, headers=h, json=data).status_code == 409
    data.update(revision=1, controls=None)
    cleared = c.put(endpoint, headers=h, json=data)
    assert cleared.status_code == 200 and cleared.json()["override"] is False
    history = c.get(endpoint).json()
    assert len(history["history"]) == 2
    for controls in ({"sp": 9.0}, {"pitch": 1}, {"ns": True}):
        data.update(revision=2, controls=controls)
        assert c.put(endpoint, headers=h, json=data).status_code == 422


def test_unapproved_target_requires_exact_revision_review_override(synthesis_project):
    c, h, _, s, line, *_ = synthesis_project
    edited = c.patch(
        path(synthesis_project) + f"/segments/{line['id']}",
        headers=h,
        json=guard(s, line["transcript_revision"])
        | {
            "revision": 1,
            "expected_source_text_fingerprint": line["source_text_fingerprint"],
            "text": "另一句話。",
            "approved": False,
        },
    )
    assert edited.status_code == 200
    request = body(synthesis_project)
    request["segments"][0]["translation_revision"] = 2
    result = c.post(path(synthesis_project) + "/synthesize", headers=h, json=request)
    assert result.status_code == 409
    assert result.json()["error"]["code"] == "TARGET_REVIEW_REQUIRED"
    request["segments"][0]["review_translation_revision"] = 2
    assert (
        c.post(path(synthesis_project) + "/synthesize", headers=h, json=request).status_code == 202
    )


def test_reference_measurements_and_exact_warning_ack_are_visible(synthesis_project):
    from test_voice_references import upload, wav_bytes

    from videotranslate.execution.worker import Worker

    c, h, p, s, line, *_ = synthesis_project
    response = upload((c, h, p), wav_bytes(1))
    assert response.status_code == 202
    assert Worker(c.app.state.settings).run_once()
    refs = c.get(f"/api/projects/{p['id']}/references").json()["items"]
    short = next(r for r in refs if r["duration_ms"] == 1000)
    assert (
        c.put(
            f"/api/projects/{p['id']}/segments/{line['id']}/reference",
            headers=h,
            json=guard(s, line["transcript_revision"])
            | {"revision": 1, "expected_segment_revision": 1, "reference_version_id": short["id"]},
        ).status_code
        == 200
    )
    listing = c.get(path(synthesis_project) + "/synthesis").json()
    assert listing["items"][0]["reference_review"] == {
        "version_id": short["id"],
        "duration_ms": 1000,
        "warnings": ["short"],
        "acknowledgement_required": True,
    }
    request = body(synthesis_project)
    denied = c.post(path(synthesis_project) + "/synthesize", headers=h, json=request)
    assert (
        denied.status_code == 409 and denied.json()["error"]["code"] == "REFERENCE_REVIEW_REQUIRED"
    )
    request["segments"][0]["review_reference_version_id"] = synthesis_project[6]["id"]
    assert (
        c.post(path(synthesis_project) + "/synthesize", headers=h, json=request).status_code == 409
    )
    request["segments"][0]["review_reference_version_id"] = short["id"]
    assert (
        c.post(path(synthesis_project) + "/synthesize", headers=h, json=request).status_code == 202
    )


def test_reads_and_commands_deny_other_workspace_and_project(
    synthesis_project, register, client_factory
):
    c, h, p, *_ = synthesis_project
    queued = c.post(
        path(synthesis_project) + "/synthesize", headers=h, json=body(synthesis_project)
    ).json()
    other = client_factory(database_url=c.app.state.settings.database_url.get_secret_value())
    auth = register(other, "foreign-synthesis@example.com")
    foreign_h = {"X-CSRF-Token": auth["csrf_token"]}
    for suffix in (
        "/synthesis",
        "/synthesis/" + queued["id"],
        f"/segments/{synthesis_project[4]['id']}/audio-history",
    ):
        assert other.get(path(synthesis_project) + suffix).status_code == 404
    assert (
        other.post(
            path(synthesis_project) + "/synthesize", headers=foreign_h, json=body(synthesis_project)
        ).status_code
        == 404
    )
    peer = c.post("/api/projects", headers=h, json={"name": "Peer"}).json()
    make_track(c, h, f"/api/projects/{peer['id']}", "zh-Hant")
    peer_base = path(synthesis_project).replace(p["id"], peer["id"])
    assert c.get(peer_base + "/synthesis/" + queued["id"]).status_code == 404
    assert (
        c.get(peer_base + f"/segments/{synthesis_project[4]['id']}/audio-history").status_code
        == 404
    )
    assert (
        c.post(path(synthesis_project) + "/synthesize", json=body(synthesis_project)).status_code
        == 403
    )
    assert c.get(path(synthesis_project) + "/synthesis", params={"limit": 101}).status_code == 422


def test_timing_edit_stales_only_source_extracted_reference_with_specific_issue(synthesis_project):
    from videotranslate.execution.worker import Worker

    c, h, p, s, line, *_ = synthesis_project
    base = f"/api/projects/{p['id']}"
    extracted = c.post(
        base + "/references/extract",
        headers=h,
        json=guard(s, line["transcript_revision"])
        | {
            "segment_id": line["id"],
            "segment_revision": 1,
            "speaker_id": None,
            "text": line["text"],
            "language": "en",
            "media": "source",
        },
    )
    assert extracted.status_code == 202
    assert Worker(c.app.state.settings).run_once()
    reference = next(
        r for r in c.get(base + "/references").json()["items"] if r["origin"] == "extracted"
    )
    assert (
        c.put(
            base + f"/segments/{line['id']}/reference",
            headers=h,
            json=guard(s, line["transcript_revision"])
            | {
                "revision": 1,
                "expected_segment_revision": 1,
                "reference_version_id": reference["id"],
            },
        ).status_code
        == 200
    )
    assert (
        c.patch(
            base + f"/segments/{line['id']}",
            headers=h,
            json=guard(s, line["transcript_revision"]) | {"revision": 1, "end_ms": 1000},
        ).status_code
        == 200
    )
    response = c.post(
        path(synthesis_project) + "/synthesize", headers=h, json=body(synthesis_project)
    )
    assert response.status_code == 409 and response.json()["error"]["code"] == "REFERENCE_STALE"
    assert c.get(path(synthesis_project) + "/synthesis").json()["items"][0]["issues"] == [
        "REFERENCE_STALE"
    ]


def test_voice_settings_read_reports_effective_provider_controls(synthesis_project):
    c, h, *_ = synthesis_project
    assert (
        c.put(
            "/api/providers/synthesis",
            headers=h,
            json={
                "revision": 1,
                "adapter": "omnivoice",
                "model": "OmniVoice",
                "space_id": "k2-fsa/OmniVoice",
                "credential_ref": None,
                "controls": {"ns": 48, "sp": 1.2},
            },
        ).status_code
        == 200
    )
    result = c.get(
        path(synthesis_project) + f"/segments/{synthesis_project[4]['id']}/voice-settings"
    ).json()
    assert result["controls"]["ns"] == 48 and result["controls"]["sp"] == 1.2

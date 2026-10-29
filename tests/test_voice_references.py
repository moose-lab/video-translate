"""Real private reference audio; CPU fixtures are not voice inference."""

import io
import struct
import wave

from dubbing_helpers import create_line, guard, selected
from sqlalchemy import select

from videotranslate.execution.worker import Worker
from videotranslate.models.core import Asset


def wav_bytes(seconds=3):
    import math

    out = io.BytesIO()
    with wave.open(out, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(
            b"".join(
                struct.pack("<h", round(math.sin(i * 2 * math.pi * 440 / 16000) * 2000))
                for i in range(round(seconds * 16000))
            )
        )
    return out.getvalue()


def upload(fixture, data=None, **fields):
    client, headers, p = fixture
    return client.post(
        f"/api/projects/{p['id']}/references/upload",
        headers=headers,
        files={"file": ("human.wav", wav_bytes() if data is None else data, "audio/wav")},
        data={"text": "Human supplied exact words", "language": "en"} | fields,
    )


def published_upload(fixture):
    client, _, p = fixture
    result = upload(fixture)
    assert result.status_code == 202, result.text
    assert result.json()["reference"] is None
    assert Worker(client.app.state.settings).run_once()
    details = client.get(f"/api/projects/{p['id']}/references").json()
    assert details["total"] == 1, details
    return details["items"][0]


def test_upload_is_queued_until_actual_decode_and_text_versions_share_audio(dubbing_project):
    client, headers, p = dubbing_project
    ref = published_upload(dubbing_project)
    assert ref["duration_ms"] == 3000 and len(ref["sha256"]) == 64
    assert ref["origin"] == "uploaded" and ref["stale"] is False
    old_asset = ref["audio_asset_id"]
    response = client.post(
        f"/api/projects/{p['id']}/references/{ref['reference_id']}/versions",
        headers=headers,
        json={"parent_version_id": ref["id"], "text": "Corrected human words", "language": "en"},
    )
    assert response.status_code == 201, response.text
    revision = response.json()
    assert revision["parent_version_id"] == ref["id"]
    assert revision["audio_asset_id"] == old_asset and revision["sha256"] == ref["sha256"]
    assert (
        client.get(f"/api/projects/{p['id']}/references/{ref['reference_id']}/versions").json()[
            "total"
        ]
        == 2
    )
    assert "storage_key" not in str(revision)


def test_declared_audio_mime_cannot_publish_nonmedia(dubbing_project):
    client, _, p = dubbing_project
    queued = upload(dubbing_project, b"not real audio")
    assert queued.status_code == 202
    assert Worker(client.app.state.settings).run_once()
    run = client.get("/api/runs/" + queued.json()["run"]["id"]).json()
    assert run["status"] == "failed" and run["safe_error"]["code"] == "INVALID_MEDIA"
    with client.app.state.session_factory() as db:
        assert (
            db.scalars(
                select(Asset).where(Asset.project_id == p["id"], Asset.kind == "voice_reference")
            ).all()
            == []
        )


def test_extract_reference_preserves_source_provenance_and_stales_after_text_edit(dubbing_project):
    client, headers, p = dubbing_project
    selection = selected(dubbing_project)
    line = create_line(dubbing_project, selection, text="exact words", start_ms=200, end_ms=1200)[
        "segment"
    ]
    body = guard(selection, line["transcript_revision"]) | {
        "segment_id": line["id"],
        "segment_revision": line["revision"],
        "speaker_id": None,
        "text": line["text"],
        "language": "en",
        "media": "source",
    }
    queued = client.post(f"/api/projects/{p['id']}/references/extract", headers=headers, json=body)
    assert queued.status_code == 202, queued.text
    assert Worker(client.app.state.settings).run_once()
    refs = client.get(f"/api/projects/{p['id']}/references").json()
    ref = refs["items"][0]
    assert ref["absolute_start_ms"] == 200 and ref["absolute_end_ms"] == 1200
    assert ref["relative_start_ms"] == 200 and ref["relative_end_ms"] == 1200
    assert ref["source_asset_id"] == p["source_asset_id"] and ref["source_segment_id"] == line["id"]
    assert ref["duration_ms"] == 1000 and "short" in ref["flags"]
    patched = client.patch(
        f"/api/projects/{p['id']}/segments/{line['id']}",
        headers=headers,
        json=guard(selection, line["transcript_revision"])
        | {"revision": line["revision"], "text": "new words"},
    )
    assert patched.status_code == 200
    refs = client.get(f"/api/projects/{p['id']}/references").json()
    assert refs["items"][0]["stale"] is True


def test_edit_between_reference_queue_and_publish_leaves_no_current_reference(dubbing_project):
    client, headers, p = dubbing_project
    selection = selected(dubbing_project)
    line = create_line(dubbing_project, selection)["segment"]
    queued = client.post(
        f"/api/projects/{p['id']}/references/extract",
        headers=headers,
        json=guard(selection, line["transcript_revision"])
        | {
            "segment_id": line["id"],
            "segment_revision": line["revision"],
            "speaker_id": None,
            "text": line["text"],
            "language": "en",
            "media": "source",
        },
    )
    assert queued.status_code == 202
    assert (
        client.patch(
            f"/api/projects/{p['id']}/segments/{line['id']}",
            headers=headers,
            json=guard(selection, line["transcript_revision"])
            | {"revision": line["revision"], "text": "changed"},
        ).status_code
        == 200
    )
    Worker(client.app.state.settings).run_once()
    assert client.get(f"/api/projects/{p['id']}/references").json()["total"] == 0


def test_default_and_override_reference_bindings_are_explicit_and_selective(dubbing_project):
    from videotranslate.dubbing.references import effective_voice_inputs
    from videotranslate.models.core import Project

    client, headers, p = dubbing_project
    selection = selected(dubbing_project)
    line = create_line(dubbing_project, selection)["segment"]
    role = client.post(
        f"/api/projects/{p['id']}/speakers", headers=headers, json={"name": "Role"}
    ).json()
    line = client.patch(
        f"/api/projects/{p['id']}/segments/{line['id']}",
        headers=headers,
        json=guard(selection, line["transcript_revision"])
        | {"revision": line["revision"], "speaker_id": role["id"]},
    ).json()
    ref = published_upload(dubbing_project)
    base = f"/api/projects/{p['id']}"
    common = guard(selection, line["transcript_revision"])
    response = client.put(
        base + "/speakers/" + role["id"] + "/reference",
        headers=headers,
        json=common
        | {
            "revision": 0,
            "reference_version_id": ref["id"],
            "expected_speaker_revision": role["revision"],
        },
    )
    assert response.status_code == 200, response.text
    default = response.json()
    assert default["revision"] == 1
    with client.app.state.session_factory() as db:
        before = effective_voice_inputs(db, db.get(Project, p["id"]), line["id"])
    response = client.put(
        base + "/segments/" + line["id"] + "/reference",
        headers=headers,
        json=common
        | {
            "revision": 0,
            "reference_version_id": ref["id"],
            "expected_segment_revision": line["revision"],
        },
    )
    assert response.status_code == 200, response.text
    with client.app.state.session_factory() as db:
        independent = effective_voice_inputs(db, db.get(Project, p["id"]), line["id"])
    assert set(before) != set(independent)
    revision = client.post(
        base + "/references/" + ref["reference_id"] + "/versions",
        headers=headers,
        json={"parent_version_id": ref["id"], "text": "new reference words", "language": "en"},
    ).json()
    assert (
        client.put(
            base + "/speakers/" + role["id"] + "/reference",
            headers=headers,
            json=common
            | {
                "revision": default["revision"],
                "reference_version_id": revision["id"],
                "expected_speaker_revision": role["revision"],
            },
        ).status_code
        == 200
    )
    with client.app.state.session_factory() as db:
        assert effective_voice_inputs(db, db.get(Project, p["id"]), line["id"]) == independent
    stale_cas = client.put(
        base + "/speakers/" + role["id"] + "/reference",
        headers=headers,
        json=common
        | {
            "revision": default["revision"],
            "reference_version_id": ref["id"],
            "expected_speaker_revision": role["revision"],
        },
    )
    assert stale_cas.status_code == 409


def test_legitimate_audio_over_json_limit_uses_upload_bound(dubbing_project):
    out = io.BytesIO()
    with wave.open(out, "wb") as wav:
        wav.setnchannels(2)
        wav.setsampwidth(2)
        wav.setframerate(48000)
        wav.writeframes(b"\x01\x00\x01\x00" * (48000 * 24))
    assert len(out.getvalue()) > 4 * 1024 * 1024
    client, _, p = dubbing_project
    result = upload(dubbing_project, out.getvalue())
    assert result.status_code == 202, result.text
    assert Worker(client.app.state.settings).run_once()
    refs = client.get(f"/api/projects/{p['id']}/references").json()
    assert refs["total"] == 1 and refs["items"][0]["duration_ms"] == 24000


def test_role_default_resolution_watches_override_discriminator(dubbing_project):
    from videotranslate.dubbing.references import effective_voice_inputs
    from videotranslate.models.core import Project

    client, headers, p = dubbing_project
    selection = selected(dubbing_project)
    line = create_line(dubbing_project, selection)["segment"]
    role = client.post(
        f"/api/projects/{p['id']}/speakers", headers=headers, json={"name": "Role"}
    ).json()
    line = client.patch(
        f"/api/projects/{p['id']}/segments/{line['id']}",
        headers=headers,
        json=guard(selection, line["transcript_revision"])
        | {"revision": line["revision"], "speaker_id": role["id"]},
    ).json()
    ref = published_upload(dubbing_project)
    assert (
        client.put(
            f"/api/projects/{p['id']}/speakers/{role['id']}/reference",
            headers=headers,
            json=guard(selection, line["transcript_revision"])
            | {
                "revision": 0,
                "reference_version_id": ref["id"],
                "expected_speaker_revision": role["revision"],
            },
        ).status_code
        == 200
    )
    with client.app.state.session_factory() as db:
        inputs = effective_voice_inputs(db, db.get(Project, p["id"]), line["id"])
    assert "voice.line:" + line["id"] in inputs
    assert "voice.role:" + role["id"] in inputs


def test_reference_parent_cannot_cross_reference_family(dubbing_project):
    import pytest
    from sqlalchemy.exc import IntegrityError

    from videotranslate.models.analysis import ReferenceVersion, VoiceReference
    from videotranslate.models.core import new_id

    client, _, p = dubbing_project
    ref = published_upload(dubbing_project)
    with pytest.raises(IntegrityError), client.app.state.session_factory.begin() as db:
        original = db.get(ReferenceVersion, ref["id"])
        root = VoiceReference(
            id=new_id(), project_id=p["id"], workspace_id=original.workspace_id, origin="uploaded"
        )
        db.add(root)
        db.flush()
        values = {
            column.name: getattr(original, column.name)
            for column in ReferenceVersion.__table__.columns
            if column.name not in {"id", "created_at", "parent_version_id", "reference_id"}
        }
        db.add(ReferenceVersion(**values, reference_id=root.id, parent_version_id=original.id))
        db.flush()


def test_extracted_reference_reports_measured_source_timing_overlap(dubbing_project):
    client, headers, p = dubbing_project
    selection = selected(dubbing_project)
    line = create_line(dubbing_project, selection, start_ms=200, end_ms=1200)["segment"]
    create_line(
        dubbing_project,
        selection,
        text="Overlapping words",
        transcript=line["transcript_revision"],
        start_ms=800,
        end_ms=1500,
    )
    queued = client.post(
        f"/api/projects/{p['id']}/references/extract",
        headers=headers,
        json=guard(selection, line["transcript_revision"])
        | {
            "segment_id": line["id"],
            "segment_revision": line["revision"],
            "speaker_id": None,
            "text": line["text"],
            "language": "en",
            "media": "source",
        },
    )
    assert queued.status_code == 202
    assert Worker(client.app.state.settings).run_once()
    ref = client.get(f"/api/projects/{p['id']}/references").json()["items"][0]
    assert "overlap" in ref["flags"] and ref["quality"] == "review_required"


def test_voice_binding_versions_are_readable_without_automatic_reference_promotion(dubbing_project):
    client, headers, p = dubbing_project
    selection = selected(dubbing_project)
    ref = published_upload(dubbing_project)
    role = client.post(
        f"/api/projects/{p['id']}/speakers", headers=headers, json={"name": "Role"}
    ).json()
    base = f"/api/projects/{p['id']}/speakers/{role['id']}/reference"
    promoted = client.put(
        base,
        headers=headers,
        json=guard(selection)
        | {
            "revision": 0,
            "expected_speaker_revision": role["revision"],
            "reference_version_id": ref["id"],
        },
    )
    assert promoted.status_code == 200
    revision = client.post(
        f"/api/projects/{p['id']}/references/{ref['reference_id']}/versions",
        headers=headers,
        json={
            "parent_version_id": ref["id"],
            "text": "Corrected but not promoted",
            "language": "en",
        },
    )
    assert revision.status_code == 201
    current = client.get(base)
    assert current.status_code == 200, current.text
    assert current.json()["reference_version_id"] == ref["id"]
    assert current.json()["history"][0]["reference_version_id"] == ref["id"]


def test_reference_domain_publication_and_corrections_advance_project_lineage(dubbing_project):
    client, headers, p = dubbing_project
    base = f"/api/projects/{p['id']}"
    before = client.get(base).json()["revision"]
    ref = published_upload(dubbing_project)
    after = client.get(base).json()["revision"]
    assert after == before + 1
    changed = client.post(
        base + "/references/" + ref["reference_id"] + "/versions",
        headers=headers,
        json={"parent_version_id": ref["id"], "text": "Corrected human words", "language": "en"},
    )
    assert changed.status_code == 201
    assert client.get(base).json()["revision"] == after + 1


def test_older_manual_rows_receive_override_discriminator_on_run_initialization(dubbing_project):
    from sqlalchemy import delete

    from videotranslate.dubbing.references import effective_voice_inputs
    from videotranslate.execution.inputs import initialize_inputs
    from videotranslate.models.core import Project
    from videotranslate.models.execution import InputState

    client, _, p = dubbing_project
    selection = selected(dubbing_project)
    line = create_line(dubbing_project, selection)["segment"]
    with client.app.state.session_factory.begin() as db:
        db.execute(
            delete(InputState).where(
                InputState.project_id == p["id"], InputState.key == "voice.line:" + line["id"]
            )
        )
        project = db.get(Project, p["id"])
        initialize_inputs(db, project)
        assert "voice.line:" + line["id"] in effective_voice_inputs(db, project, line["id"])

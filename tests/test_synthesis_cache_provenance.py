"""Prepared natural audio requires complete immutable provider and decode provenance."""
# ruff: noqa: F811

import copy

import pytest
from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified
from test_synthesis_domain import body, path, synthesis_project  # noqa: F401
from test_synthesis_operations import history, install_clone, queue
from test_translation_operations import drain

from videotranslate.models.analysis import PreparedObject, PrivateOperation
from videotranslate.models.core import Project
from videotranslate.models.execution import StageRun
from videotranslate.models.synthesis import SynthesisLine


def producing_operation(db):
    return db.scalar(select(PrivateOperation).join(StageRun).where(StageRun.stage == "synthesize"))


@pytest.mark.parametrize(
    "corruption",
    [
        "provider",
        "model",
        "connection_revision",
        "host",
        "prefix",
        "remote_id",
        "api_name",
        "metadata_revision",
        "schema_sha256",
        "language_enum",
        "model_language",
        "args",
        "uploaded_reference",
        "terminal_file",
        "raw_missing",
        "raw_sha",
        "raw_duration_bool",
        "raw_duration_float",
        "raw_duration_zero",
        "raw_duration_limit",
        "raw_rate",
        "raw_channels",
        "raw_bytes",
        "raw_container",
        "raw_codec",
        "raw_extra",
        "raw_wav_relationship",
        "record_raw_proof",
        "record_version_bool",
    ],
)
def test_corrupted_origin_evidence_is_not_reused(
    synthesis_project, monkeypatch, tmp_path, corruption
):
    c, h, *_ = synthesis_project
    http = install_clone(monkeypatch, tmp_path)
    queued = queue(synthesis_project)
    drain(c)
    with c.app.state.session_factory.begin() as db:
        operation = producing_operation(db)
        if corruption in {
            "provider",
            "model",
            "connection_revision",
            "host",
            "prefix",
            "remote_id",
        }:
            values = {
                "provider": "demucs",
                "model": "wrong-model",
                "connection_revision": 101,
                "host": "https://another.hf.space",
                "prefix": "",
                "remote_id": "another-event",
            }
            setattr(operation, corruption, values[corruption])
        elif corruption == "terminal_file":
            terminal = copy.deepcopy(operation.terminal_payload)
            terminal["audio"]["path"] = "/another-terminal-file.wav"
            operation.terminal_payload = terminal
        elif corruption in {
            "api_name",
            "metadata_revision",
            "schema_sha256",
            "language_enum",
            "model_language",
            "args",
            "uploaded_reference",
        }:
            request = copy.deepcopy(operation.request_payload)
            prepared = request["prepared"]
            if corruption == "args":
                prepared["args"][0] = "wrong private wording"
            elif corruption == "uploaded_reference":
                prepared["args"][2]["path"] = "/another-upload.wav"
            else:
                prepared[corruption] = {
                    "api_name": "wrong_api",
                    "metadata_revision": "another-revision",
                    "schema_sha256": "a" * 64,
                    "language_enum": ["CHINESE"],
                    "model_language": "CHINESE",
                }[corruption]
            operation.request_payload = request
        elif corruption in {"record_raw_proof", "record_version_bool"}:
            record = db.get(PreparedObject, operation.prepared_payload["objects"][0])
            evidence = copy.deepcopy(record.metadata_json)
            if corruption == "record_version_bool":
                evidence["provenance"]["version"] = True
            else:
                evidence.pop("provenance", None)
            record.metadata_json = evidence
            flag_modified(record, "metadata_json")
        else:
            payload = copy.deepcopy(operation.prepared_payload)
            raw = payload["raw_metadata"]
            if corruption == "raw_missing":
                payload["raw_metadata"] = {}
            elif corruption == "raw_extra":
                raw["private_path"] = "/not-measurement"
            else:
                field, value = {
                    "raw_sha": ("sha256", "b" * 64),
                    "raw_duration_bool": ("duration_ms", True),
                    "raw_duration_float": ("duration_ms", 600.0),
                    "raw_duration_zero": ("duration_ms", 0),
                    "raw_duration_limit": ("duration_ms", 600001),
                    "raw_rate": ("sample_rate", 0),
                    "raw_channels": ("channels", 9),
                    "raw_bytes": ("byte_size", 64 * 1024 * 1024 + 1),
                    "raw_container": ("container", "zip"),
                    "raw_codec": ("codec", "unknown"),
                    "raw_wav_relationship": ("sample_rate", 48000),
                }[corruption]
                raw[field] = value
            operation.prepared_payload = payload
            flag_modified(operation, "prepared_payload")
    request = body(synthesis_project, replace_selected=True)
    request["segments"][0]["selection_revision"] = 1
    response = c.post(path(synthesis_project) + "/synthesize", headers=h, json=request)
    assert response.status_code == 202, response.text
    drain(c)
    assert len(http.posts) == 2, corruption
    assert history(synthesis_project)["selection_revision"] == 2
    # Immutable historical output is retained, with invalid evidence explicitly visible.
    older = next(
        x for x in history(synthesis_project)["outputs"] if x["line_id"] == queued["lines"][0]["id"]
    )
    assert older["evidence_status"] == "invalid"


@pytest.mark.parametrize(
    "field,value",
    [
        ("provider", "demucs"),
        ("model", "wrong-model"),
        ("connection_revision", 101),
        ("host", "https://another.hf.space"),
        ("prefix", "/gradio_api"),
    ],
)
def test_reuse_alias_requires_its_own_captured_operation_binding(
    synthesis_project, monkeypatch, tmp_path, field, value
):
    from videotranslate.dubbing.synthesis_cache import cached_payload

    c, h, p, *_ = synthesis_project
    http = install_clone(monkeypatch, tmp_path)
    queue(synthesis_project)
    drain(c)
    request = body(synthesis_project, replace_selected=True)
    request["segments"][0]["selection_revision"] = 1
    result = c.post(path(synthesis_project) + "/synthesize", headers=h, json=request).json()
    drain(c)
    assert len(http.posts) == 1
    with c.app.state.session_factory.begin() as db:
        alias = db.get(SynthesisLine, result["lines"][0]["id"])
        operation = db.scalar(
            select(PrivateOperation).where(PrivateOperation.run_id == alias.run_id)
        )
        setattr(operation, field, value)
    with c.app.state.session_factory() as db, pytest.raises(ValueError):
        cached_payload(db, db.get(Project, p["id"]), db.get(SynthesisLine, alias.id))


def test_valid_multiple_aliases_share_original_validated_provenance_without_posts(
    synthesis_project, monkeypatch, tmp_path
):
    c, h, *_ = synthesis_project
    http = install_clone(monkeypatch, tmp_path)
    queue(synthesis_project)
    drain(c)
    for revision in (1, 2, 3):
        request = body(synthesis_project, replace_selected=True)
        request["segments"][0]["selection_revision"] = revision
        assert (
            c.post(path(synthesis_project) + "/synthesize", headers=h, json=request).status_code
            == 202
        )
        drain(c)
    assert len(http.posts) == 1 and history(synthesis_project)["selection_revision"] == 4
    assert all(
        row["evidence_status"] == "validated" for row in history(synthesis_project)["outputs"]
    )


def test_invalid_provenance_remains_visible_but_cannot_be_manually_selected(
    synthesis_project, monkeypatch, tmp_path
):
    from dubbing_helpers import guard

    c, h, _, source, line, *_ = synthesis_project
    install_clone(monkeypatch, tmp_path)
    queue(synthesis_project)
    drain(c)
    output = history(synthesis_project)["outputs"][0]
    with c.app.state.session_factory.begin() as db:
        producing_operation(db).provider = "demucs"
    assert history(synthesis_project)["outputs"][0]["evidence_status"] == "invalid"
    response = c.put(
        path(synthesis_project) + f"/segments/{line['id']}/audio-selection",
        headers=h,
        json=guard(source, line["transcript_revision"])
        | {
            "revision": 1,
            "output_id": output["id"],
            "translation_revision": 1,
            "expected_source_text_fingerprint": line["source_text_fingerprint"],
        },
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "AUDIO_EVIDENCE_INVALID"
    assert history(synthesis_project)["selection_revision"] == 1


def measurement_pair():
    raw = {
        "duration_ms": 1000,
        "sample_rate": 16000,
        "channels": 1,
        "byte_size": 4096,
        "sha256": "a" * 64,
        "codec": "mp3",
        "container": "mp3",
    }
    natural = raw | {
        "sample_rate": 48000,
        "byte_size": 96044,
        "sha256": "b" * 64,
        "codec": "pcm_s16le",
        "container": "wav",
    }
    return raw, natural


@pytest.mark.parametrize("delta", [-80, 0, 80])
def test_raw_normalized_measurements_preserve_decode_duration_tolerance(delta):
    from videotranslate.dubbing.synthesis_evidence import validate_audio_pair

    raw, natural = measurement_pair()
    natural["duration_ms"] += delta
    assert validate_audio_pair(raw, natural) == (raw, natural)


@pytest.mark.parametrize(
    "side,field,value",
    [
        ("raw", "sha256", "invalid-hash"),
        ("raw", "duration_ms", 1000.0),
        ("raw", "sample_rate", True),
        ("raw", "channels", 1.0),
        ("raw", "byte_size", False),
        ("raw", "codec", "unknown"),
        ("raw", "container", "zip"),
        ("natural", "duration_ms", 1081),
        ("natural", "sample_rate", 16000),
        ("natural", "channels", 2),
        ("natural", "sha256", "a" * 64),
        ("natural", "container", "mp3"),
        ("natural", "codec", "pcm_f32le"),
    ],
)
def test_raw_normalized_measurements_reject_invalid_types_and_contradictions(side, field, value):
    from videotranslate.dubbing.synthesis_evidence import validate_audio_pair

    raw, natural = measurement_pair()
    (raw if side == "raw" else natural)[field] = value
    with pytest.raises(ValueError):
        validate_audio_pair(raw, natural)


@pytest.mark.parametrize(
    "corruption", ["origin_reused_fact", "alias_reused_fact", "alias_remote_state"]
)
def test_cache_alias_and_real_submission_facts_cannot_be_interchanged(
    synthesis_project, monkeypatch, tmp_path, corruption
):
    from videotranslate.dubbing.synthesis_cache import cached_payload

    c, h, p, *_ = synthesis_project
    install_clone(monkeypatch, tmp_path)
    original = queue(synthesis_project)
    drain(c)
    selected_id = original["lines"][0]["id"]
    if corruption != "origin_reused_fact":
        request = body(synthesis_project, replace_selected=True)
        request["segments"][0]["selection_revision"] = 1
        result = c.post(path(synthesis_project) + "/synthesize", headers=h, json=request).json()
        drain(c)
        selected_id = result["lines"][0]["id"]
    with c.app.state.session_factory.begin() as db:
        line = db.get(SynthesisLine, selected_id)
        operation = db.scalar(
            select(PrivateOperation).where(PrivateOperation.run_id == line.run_id)
        )
        if corruption == "alias_remote_state":
            db.get(StageRun, line.run_id).remote_state = "submitted"
        else:
            operation.public_facts = operation.public_facts | {
                "reused": corruption == "origin_reused_fact"
            }
    with c.app.state.session_factory() as db, pytest.raises(ValueError):
        cached_payload(db, db.get(Project, p["id"]), db.get(SynthesisLine, selected_id))


@pytest.mark.parametrize("producing", [True, False])
def test_operation_request_requires_exact_canonical_json_types(
    synthesis_project, monkeypatch, tmp_path, producing
):
    from videotranslate.dubbing.synthesis_evidence import validate_operation

    c, h, *_ = synthesis_project
    install_clone(monkeypatch, tmp_path)
    result = queue(synthesis_project)
    drain(c)
    if not producing:
        request = body(synthesis_project, replace_selected=True)
        request["segments"][0]["selection_revision"] = 1
        result = c.post(path(synthesis_project) + "/synthesize", headers=h, json=request).json()
        drain(c)
    with c.app.state.session_factory.begin() as db:
        line = db.get(SynthesisLine, result["lines"][0]["id"])
        operation = db.scalar(
            select(PrivateOperation).where(PrivateOperation.run_id == line.run_id)
        )
        payload = copy.deepcopy(operation.request_payload)
        if producing:
            payload["prepared"]["args"][5] = 32.0
        else:
            payload["input"]["controls"]["ns"] = 32.0
        operation.request_payload = payload
        flag_modified(operation, "request_payload")
    with c.app.state.session_factory() as db, pytest.raises(ValueError):
        line = db.get(SynthesisLine, result["lines"][0]["id"])
        operation = db.scalar(
            select(PrivateOperation).where(PrivateOperation.run_id == line.run_id)
        )
        validate_operation(operation, line.input_payload, producing=producing)

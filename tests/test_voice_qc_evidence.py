"""Immutable original recognition provenance and exact alias bindings."""

# ruff: noqa: F811
import copy

import pytest
from sqlalchemy import select
from test_synthesis_domain import synthesis_project  # noqa: F401
from test_translation_operations import drain
from test_voice_qc_operations import enqueue, prepared


@pytest.mark.parametrize(
    "corruption",
    [
        "run_provider",
        "run_model",
        "run_remote_id",
        "run_remote_state",
        "request_extra",
        "request_numeric",
        "payload_extra",
        "metadata_bool",
        "metadata_hash",
        "record_state",
        "working_timings",
        "reported_language",
        "historical_config",
    ],
)
def test_saved_recognition_rejects_inconsistent_evidence(
    synthesis_project, monkeypatch, tmp_path, corruption
):
    from videotranslate.dubbing.remote_voice_qc import cached_recognition
    from videotranslate.errors import APIError
    from videotranslate.models.analysis import PreparedObject, PrivateOperation
    from videotranslate.models.core import Project
    from videotranslate.models.execution import StageRun
    from videotranslate.models.voice_qc import VoiceQCLine

    prepared(synthesis_project, monkeypatch, tmp_path)
    enqueue(synthesis_project)
    drain(synthesis_project[0])
    c = synthesis_project[0]
    with c.app.state.session_factory.begin() as db:
        line = db.scalar(select(VoiceQCLine))
        run = db.get(StageRun, line.run_id)
        operation = db.scalar(select(PrivateOperation).where(PrivateOperation.run_id == run.id))
        payload = copy.deepcopy(operation.prepared_payload)
        if corruption.startswith("run_"):
            setattr(
                run,
                corruption[4:],
                "not_submitted" if corruption == "run_remote_state" else "wrong",
            )
        elif corruption == "request_numeric":
            request = copy.deepcopy(operation.request_payload)
            request["input"]["connection_revision"] = float(request["input"]["connection_revision"])
            operation.request_payload = request
            from sqlalchemy.orm.attributes import flag_modified

            flag_modified(operation, "request_payload")
        elif corruption == "request_extra":
            operation.request_payload = operation.request_payload | {"fake": True}
        elif corruption == "payload_extra":
            payload["fake"] = True
        elif corruption in {"metadata_bool", "metadata_hash"}:
            field, value = (
                ("byte_size", True) if corruption == "metadata_bool" else ("sha256", "bad")
            )
            payload["preprocessing"][field] = value
            operation.request_payload = operation.request_payload | {
                "preprocessing": payload["preprocessing"]
            }
            record = db.get(PreparedObject, payload["objects"][0])
            record.metadata_json = payload["preprocessing"] | {"kind": "voice_qc_input"}
        elif corruption == "record_state":
            db.get(PreparedObject, payload["objects"][0]).delete_pending = True
        elif corruption == "working_timings":
            payload["working_timings"] = []
        elif corruption == "reported_language":
            payload["recognition"]["detected_language"] = "https://private.example/secret"
        else:
            line.recognition_input = line.recognition_input | {"connection_revision": 999}
        operation.prepared_payload = payload
        db.flush()
        with pytest.raises((APIError, ValueError, TypeError, KeyError)):
            cached_recognition(db, db.get(Project, line.project_id), line)

"""Model-specific timestamp-tail regression; recorded HF data, no live inference."""

import json
import subprocess
from datetime import timedelta

import pytest
from dubbing_helpers import select_source
from sqlalchemy import select
from test_analysis_quality_fixes import analysis
from test_analysis_workflow import configure_remote, recording_provider, timeline

from videotranslate.dubbing.analysis import cached_analysis, transcribe_handler, working_timings
from videotranslate.dubbing.analysis_contracts import NormalizedTranscript
from videotranslate.errors import APIError
from videotranslate.execution.context import RunContext
from videotranslate.execution.service import claim_run
from videotranslate.execution.worker import Worker
from videotranslate.models.analysis import PrivateOperation
from videotranslate.models.core import Project, utcnow
from videotranslate.models.dubbing import TranscriptRevision
from videotranslate.models.execution import StageRun
from videotranslate.providers.whisper import normalize_asr

WHISPER = "openai/whisper-large-v3"
ACTUAL_TAIL = {
    "text": " You've likely heard about prompt engineering,",
    "timestamp": [57.06, 59.52],
}


@pytest.mark.parametrize(
    "provider,model,end,accepted,clipped",
    [
        ("hf_asr", WHISPER, 59.51, True, False),
        ("hf_asr", WHISPER, 59.52, True, True),
        ("hf_asr", WHISPER, 59.53, True, True),
        ("hf_asr", WHISPER, 59.530001, False, False),
        ("hf_asr", "other/unknown-model", 59.52, False, False),
        ("hf_asr", None, 59.52, False, False),
        ("other", WHISPER, 59.52, False, False),
        ("nvidia_stream", None, 59.56, True, True),
        ("nvidia_stream", None, 59.560001, False, False),
    ],
)
def test_only_known_whisper_gets_20ms_quantization_tail(provider, model, end, accepted, clipped):
    rows = [{"start": 57.06, "end": end, "text": ACTUAL_TAIL["text"]}]
    original = [dict(row) for row in rows]
    if not accepted:
        with pytest.raises(ValueError):
            working_timings(rows, 59510, provider, model=model)
    else:
        result = working_timings(rows, 59510, provider, model=model)
        assert result == [
            {
                "start_ms": 57060,
                "end_ms": 59510,
                "flags": ["provider_end_clipped"] if clipped else [],
            }
        ]
    assert rows == original


def test_actual_59510_to_59520_wire_row_keeps_typed_original_seconds_and_text():
    rows = normalize_asr({"chunks": [ACTUAL_TAIL]})
    payload = NormalizedTranscript(selection_id="selection", segments=rows)
    originals = [row.model_dump() for row in payload.segments]
    assert originals[0]["end"] == 59.52 and originals[0]["text"] == ACTUAL_TAIL["text"]
    assert working_timings(originals, 59510, "hf_asr", model=WHISPER)[0] == {
        "start_ms": 57060,
        "end_ms": 59510,
        "flags": ["provider_end_clipped"],
    }
    assert originals[0]["end"] == 59.52


def test_known_whisper_prepared_recovery_publishes_flag_and_replays_without_post(
    dubbing_project, monkeypatch, tmp_path
):
    client, headers, _ = dubbing_project
    path = tmp_path / "sixty-second-fixture.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=s=32x32:r=5",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440",
            "-t",
            "60",
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            "-shortest",
            str(path),
        ],
        check=True,
    )
    base = f"/api/projects/{dubbing_project[2]['id']}"
    uploaded = client.post(
        base + "/source",
        headers=headers,
        files={"file": (path.name, path.read_bytes(), "video/mp4")},
    )
    assert uploaded.status_code == 201
    project = uploaded.json()["project"]
    fixture = client, headers, project
    assert client.post(base + "/runs", headers=headers, json={"stage": "probe"}).status_code == 201
    worker = Worker(client.app.state.settings)
    assert worker.run_once()
    selection = select_source(fixture, end_ms=59510)
    assert selection.status_code == 200
    configure_remote(fixture)
    provider = recording_provider(monkeypatch, client)
    original_post = provider.post_json

    def wire_response(self, url, body, **kw):
        result = original_post(self, url, body, **kw)
        return json.dumps({"chunks": [ACTUAL_TAIL]}).encode() if "/hf-inference/" in url else result

    monkeypatch.setattr(provider, "post_json", wire_response)
    first = analysis(fixture)
    assert worker.run_once() and worker.run_once()  # Real CPU preparation, recorded separation.
    sf = client.app.state.session_factory
    with sf.begin() as db:
        run = claim_run(db, "before-whisper-publication")
        assert run.stage == "transcribe"
    context = RunContext(
        sf, client.app.state.storage, client.app.state.settings, run.id, run.lease_token
    )
    result = transcribe_handler(context)  # Durable private success, simulated process restart.
    with sf.begin() as db:
        operation = db.get(PrivateOperation, result.prepared_id)
        assert (
            operation.model == WHISPER and operation.prepared_payload["segments"][0]["end"] == 59.52
        )
        db.get(StageRun, run.id).lease_expires_at = utcnow() - timedelta(seconds=1)
    before = list(provider.posts)
    assert Worker(client.app.state.settings).run_once()
    assert provider.posts == before
    current = timeline(fixture)
    assert current["segments"][0]["end_ms"] == 59510
    assert current["segments"][0]["source_analysis_flags"] == ["provider_end_clipped"]
    assert current["segments"][0]["text"] == ACTUAL_TAIL["text"]
    with sf.begin() as db:
        transcript = db.get(TranscriptRevision, current["transcript"]["id"])
        assert transcript.original_segments[0]["end"] == 59.52
        assert transcript.original_segments[0]["text"] == ACTUAL_TAIL["text"]
        source = db.get(StageRun, run.id)
        project_row = db.get(Project, project["id"])
        assert (
            cached_analysis(db, project_row, run.id, source.dependency_snapshot)[1].id
            == result.prepared_id
        )
        operation = db.get(PrivateOperation, result.prepared_id)
        operation.model = "other/unknown-model"
        with pytest.raises(APIError):
            cached_analysis(db, project_row, run.id, source.dependency_snapshot)
        operation.model = WHISPER
    second = analysis(fixture)
    assert second["id"] != first["id"]
    assert Worker(client.app.state.settings).run_once()
    assert provider.posts == before
    assert timeline(fixture)["transcript"]["id"] == current["transcript"]["id"]
    with sf() as db:
        assert db.get(StageRun, run.id).status == "succeeded"
        assert (
            db.scalar(
                select(PrivateOperation).where(PrivateOperation.id == result.prepared_id)
            ).model
            == WHISPER
        )

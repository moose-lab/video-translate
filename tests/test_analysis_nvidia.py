"""Recorded NVIDIA contract double with real PCM preparation; never inference proof."""

from dubbing_helpers import selected
from sqlalchemy import select
from test_analysis_workflow import configure_remote, recording_provider, timeline

from videotranslate.execution.worker import Worker
from videotranslate.models.analysis import PrivateOperation


def test_nvidia_registered_handler_keeps_real_labels_and_has_no_fake_poll_id(
    dubbing_project, monkeypatch
):
    client, headers, project = dubbing_project
    selected(dubbing_project)
    configure_remote(dubbing_project, adapter="nvidia_stream")
    recording_provider(monkeypatch, client)

    def recorded_stream(pcm, **kw):
        assert len(pcm) == 2 * 16000 * 2
        assert kw["source_language"] == "en"
        kw["before_send"]()
        with client.app.state.session_factory() as db:
            op = db.scalar(
                select(PrivateOperation).where(PrivateOperation.provider == "nvidia_stream")
            )
            assert op.phase == "submitting" and op.remote_id is None
        return [
            {"start": 0.1, "end": 0.9, "text": "first real label", "speaker": "speaker_0"},
            {"start": 0.8, "end": 1.8, "text": "second real label", "speaker": "speaker_1"},
        ]

    monkeypatch.setattr("videotranslate.providers.nvidia_stream.stream_remote", recorded_stream)
    base = f"/api/projects/{project['id']}"
    current_project = client.get(base).json()
    assert (
        client.patch(
            base,
            headers=headers,
            json={"revision": current_project["revision"], "source_language": "en"},
        ).status_code
        == 200
    )
    response = client.post(
        base + "/workflow",
        headers=headers,
        json={
            "action": "analyse",
            "expected_editor_fingerprint": timeline(dubbing_project)["editor_fingerprint"],
        },
    )
    assert response.status_code == 202
    worker = Worker(client.app.state.settings)
    for _ in range(3):
        assert worker.run_once()
    current = timeline(dubbing_project)
    assert [row["text"] for row in current["segments"]] == ["first real label", "second real label"]
    assert {row["name"] for row in current["cast"]} == {"speaker_0", "speaker_1"}
    assert current["segments"][0]["speaker_id"] != current["segments"][1]["speaker_id"]
    with client.app.state.session_factory() as db:
        op = db.scalar(select(PrivateOperation).where(PrivateOperation.provider == "nvidia_stream"))
        assert op.phase == "prepared" and op.remote_id is None
        assert op.prepared_payload["segments"][1]["start"] == 0.8

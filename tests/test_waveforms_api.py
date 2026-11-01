"""Owned worker waveform admission, cache, and read-only preview contracts."""
# ruff: noqa: F811

import pytest
from dubbing_helpers import guard, selected
from sqlalchemy import event, select
from test_synthesis_domain import synthesis_project  # noqa: F401
from test_synthesis_operations import history, install_clone, queue
from test_translation_operations import drain

from videotranslate.models.analysis import PrivateOperation
from videotranslate.models.execution import StageRun


def endpoint(f):
    return f"/api/projects/{f[2]['id']}/waveforms"


def test_source_requires_preparation_then_actual_durable_waveform(dubbing_project):
    c, h, p = dubbing_project
    selection = selected(dubbing_project)
    body = dict(guard=guard(selection), kind="source", bins=7)
    discovery = c.get(endpoint(dubbing_project))
    assert discovery.status_code == 200, discovery.text
    assert not discovery.json()["source"]["available"]
    assert discovery.json()["source"]["preparation_hint"]
    assert c.post(endpoint(dubbing_project), headers=h, json=body).status_code == 409
    c.post(f"/api/projects/{p['id']}/runs", headers=h, json={"stage": "extract"})
    drain(c)
    admitted = c.post(endpoint(dubbing_project), headers=h, json=body)
    assert admitted.status_code == 202, admitted.text
    pending = admitted.json()
    assert pending["status"] == "queued" and pending["waveform"] is None
    assert c.post(endpoint(dubbing_project), headers=h, json=body).json()["id"] == pending["id"]
    drain(c)
    result = c.get(endpoint(dubbing_project) + "/" + pending["id"]).json()
    assert result["status"] == "succeeded", result
    assert result["current"] and result["waveform"]["bin_count"] == 7
    assert result["waveform"]["clock"] == "source_selection_relative"
    assert result["waveform"]["sample_count"] == 96000
    assert result["waveform"]["channels"] == 2
    assert any(b["rms"] > 0 for b in result["waveform"]["bins"])
    assert c.get(result["artifact"]["url"]).status_code == 200
    assert c.post(endpoint(dubbing_project), headers=h, json=body).json()["id"] == pending["id"]
    assert c.post(endpoint(dubbing_project), json=body).status_code == 403
    assert (
        c.post(endpoint(dubbing_project), headers=h, json=body | {"bins": 2001}).status_code == 422
    )


def test_natural_voice_uses_selected_output_proof_and_own_clock(
    synthesis_project, monkeypatch, tmp_path
):
    f = synthesis_project
    c, h, _, selection, line, *_ = f
    install_clone(monkeypatch, tmp_path)
    queue(f)
    drain(c)
    output = history(f)["selected_output_id"]
    body = dict(
        guard=guard(selection, line["transcript_revision"]),
        kind="natural_voice",
        output_id=output,
        bins=10,
    )
    response = c.post(endpoint(f), headers=h, json=body)
    assert response.status_code == 202, response.text
    drain(c)
    result = c.get(endpoint(f) + "/" + response.json()["id"]).json()
    assert result["status"] == "succeeded", result
    assert result["waveform"]["clock"] == "natural_audio_relative"
    assert result["waveform"]["provenance"]["output_id"] == output
    assert result["waveform"]["input_sha256"] == history(f)["outputs"][0]["sha256"]
    assert c.post(endpoint(f), headers=h, json=body | {"output_id": "foreign"}).status_code == 404

    # The same audio bytes with a new explicit selection version are a new preview input.
    def reselect():
        selected_again = c.put(
            f"/api/projects/{f[2]['id']}/language-tracks/{f[5]['tag']}/segments/{line['id']}/audio-selection",
            headers=h,
            json=body["guard"]
            | dict(
                revision=history(f)["selection_revision"],
                output_id=output,
                translation_revision=1,
                expected_source_text_fingerprint=line["source_text_fingerprint"],
            ),
        )
        assert selected_again.status_code == 200, selected_again.text

    reselect()
    assert not c.get(endpoint(f) + "/" + response.json()["id"]).json()["current"]
    later = c.post(endpoint(f), headers=h, json=body).json()
    from videotranslate.dubbing import waveforms_execution

    compute = waveforms_execution.envelope

    def changed_during_compute(*args, **kwargs):
        actual = compute(*args, **kwargs)
        reselect()
        return actual

    monkeypatch.setattr(waveforms_execution, "envelope", changed_during_compute)
    drain(c)
    stale = c.get(endpoint(f) + "/" + later["id"]).json()
    assert stale["status"] == "stale" and stale["artifact"] is None


def prepared_source(f):
    c, h, p = f
    selection = selected(f)
    c.post(f"/api/projects/{p['id']}/runs", headers=h, json={"stage": "extract"})
    drain(c)
    return dict(guard=guard(selection), kind="source", bins=25)


def test_get_discovery_and_detail_never_write_sql_or_compute(dubbing_project, monkeypatch):
    from videotranslate.media import waveform

    f = dubbing_project
    c, h, _ = f
    body = prepared_source(f)
    run = c.post(endpoint(f), headers=h, json=body).json()
    drain(c)

    def forbidden(*args, **kwargs):
        raise AssertionError("GET must not compute")

    writes = []

    def sql(conn, cursor, statement, *args):
        if statement.lstrip().upper().startswith(("UPDATE", "INSERT", "DELETE")):
            writes.append(statement)

    monkeypatch.setattr(waveform, "envelope", forbidden)
    event.listen(c.app.state.engine, "before_cursor_execute", sql)
    try:
        assert c.get(endpoint(f)).status_code == 200
        response = c.get(endpoint(f) + "/" + run["id"])
        assert response.status_code == 200 and response.json()["waveform"]
    finally:
        event.remove(c.app.state.engine, "before_cursor_execute", sql)
    assert writes == []


def test_worker_restarts_from_validated_checkpoint_without_recompute(dubbing_project, monkeypatch):
    from dataclasses import replace

    from videotranslate.dubbing import waveforms_execution
    from videotranslate.execution.registry import STAGES

    f = dubbing_project
    c, h, _ = f
    body = prepared_source(f)
    run = c.post(endpoint(f), headers=h, json=body).json()
    definition = STAGES["waveform_envelope"]

    def crash(*args):
        raise RuntimeError("Test publisher crash after durable CPU checkpoint")

    monkeypatch.setitem(STAGES, "waveform_envelope", replace(definition, publish=crash))
    drain(c)
    assert c.get(endpoint(f) + "/" + run["id"]).json()["status"] == "failed"
    with c.app.state.session_factory() as db:
        operation = db.scalar(select(PrivateOperation).where(PrivateOperation.run_id == run["id"]))
        assert operation.phase == "prepared"
        checkpoint_id = operation.id
    monkeypatch.setitem(STAGES, "waveform_envelope", definition)

    def forbidden(*args, **kwargs):
        raise AssertionError("Restart must use actual durable artifact")

    monkeypatch.setattr(waveforms_execution, "envelope", forbidden)
    retry = c.post(f"/api/runs/{run['id']}/retry", headers=h, json={})
    assert retry.status_code == 200, retry.text
    drain(c)
    result = c.get(endpoint(f) + "/" + run["id"]).json()
    assert result["status"] == "succeeded", result
    with c.app.state.session_factory() as db:
        operation = db.scalar(select(PrivateOperation).where(PrivateOperation.run_id == run["id"]))
        assert operation.id == checkpoint_id


def test_wrong_guard_foreign_project_and_changed_source_are_rejected(
    dubbing_project, client_factory, register
):
    f = dubbing_project
    c, h, p = f
    body = prepared_source(f)
    assert (
        c.post(
            endpoint(f),
            headers=h,
            json=body | {"guard": body["guard"] | {"selection_revision": 999}},
        ).status_code
        == 409
    )
    run = c.post(endpoint(f), headers=h, json=body).json()
    other_project = c.post("/api/projects", headers=h, json={"name": "Other"}).json()
    assert c.get(f"/api/projects/{other_project['id']}/waveforms/{run['id']}").status_code == 404
    stranger = client_factory(database_url=c.app.state.settings.database_url.get_secret_value())
    register(stranger, "stranger-waveform@example.com")
    assert stranger.get(endpoint(f)).status_code == 404
    latest = c.get(f"/api/projects/{p['id']}").json()
    response = c.put(
        f"/api/projects/{p['id']}/source-selection",
        headers=h,
        json=dict(
            revision=latest["revision"],
            source_asset_id=p["source_asset_id"],
            audio_ordinal=0,
            start_ms=500,
            end_ms=1500,
        ),
    )
    assert response.status_code == 200, response.text
    drain(c)
    result = c.get(endpoint(f) + "/" + run["id"]).json()
    assert not result["current"] and result["artifact"] is None


def test_cancellation_and_corrupted_private_artifact_are_explicit(dubbing_project):
    f = dubbing_project
    c, h, _ = f
    body = prepared_source(f)
    cancelled = c.post(endpoint(f), headers=h, json=body).json()
    assert c.post(f"/api/runs/{cancelled['id']}/cancel", headers=h).status_code == 200
    drain(c)
    assert c.get(endpoint(f) + "/" + cancelled["id"]).json()["artifact"] is None
    run = c.post(endpoint(f), headers=h, json=body | {"bins": 50}).json()
    drain(c)
    state = c.get(endpoint(f) + "/" + run["id"]).json()
    with c.app.state.session_factory() as db:
        from videotranslate.models.core import Asset

        asset = db.get(Asset, state["artifact"]["asset_id"])
        key = asset.storage_key
        assert db.get(StageRun, run["id"]).result.keys() == {
            "sample_count",
            "sample_rate",
            "channels",
            "bin_count",
        }
    import io

    c.app.state.storage.put(key, io.BytesIO(b"{}"), "application/json")
    direct = c.get(state["artifact"]["url"])
    assert (
        direct.status_code == 409 and direct.json()["error"]["code"] == "WAVEFORM_ARTIFACT_INVALID"
    )
    result = c.get(endpoint(f) + "/" + run["id"]).json()
    assert result["waveform"] is None and result["error"]["code"] == "WAVEFORM_ARTIFACT_INVALID"


@pytest.mark.parametrize(
    "field,value",
    [
        ("storage_key", "foreign/private/object"),
        ("sha256", "0" * 64),
        ("byte_size", 1),
        ("kind", "source_video"),
        ("content_type", "video/mp4"),
    ],
)
def test_published_asset_must_match_exact_owned_prepared_manifest(dubbing_project, field, value):
    from sqlalchemy import update

    from videotranslate.models.core import Asset

    f = dubbing_project
    c, h, _ = f
    body = prepared_source(f)
    admitted = c.post(endpoint(f), headers=h, json=body).json()
    drain(c)
    result = c.get(endpoint(f) + "/" + admitted["id"]).json()
    saved_url = result["artifact"]["url"]
    with c.app.state.session_factory.begin() as db:
        db.execute(
            update(Asset).where(Asset.id == result["artifact"]["asset_id"]).values({field: value})
        )
    rejected = c.get(endpoint(f) + "/" + admitted["id"]).json()
    assert rejected["waveform"] is None and rejected["artifact"] is None
    direct = c.get(saved_url)
    assert (
        direct.status_code == 409 and direct.json()["error"]["code"] == "WAVEFORM_ARTIFACT_INVALID"
    )

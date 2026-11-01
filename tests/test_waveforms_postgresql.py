"""Focused exact-window and duplicate-admission proof on actual SQL backends."""

import os
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from dubbing_helpers import guard, make_probed_project, select_source
from test_translation_operations import drain
from test_waveforms_api import endpoint


@pytest.mark.parametrize("backend", ["sqlite", "postgresql"])
def test_owned_window_and_concurrent_cache_admission(client_factory, register, tmp_path, backend):
    admin = client = None
    if backend == "postgresql":
        import psycopg
        from psycopg import sql

        url = os.environ.get("VT_TEST_POSTGRES_ADMIN_URL")
        if not url:
            pytest.skip("Opt-in isolated PostgreSQL unavailable")
        name = "waveform_runtime_" + uuid4().hex
        admin = psycopg.connect(url, autocommit=True)
        admin.execute(sql.SQL("CREATE DATABASE {} OWNER vt_test").format(sql.Identifier(name)))
        url = (url.rsplit("/", 1)[0] + "/" + name).replace("postgresql://", "postgresql+psycopg://")
    else:
        url = f"sqlite:///{tmp_path}/waveform.db"
    try:
        f = make_probed_project(lambda: client_factory(database_url=url), register, tmp_path)
        client, headers, project = f
        selected = select_source(f, start_ms=500, end_ms=1500)
        assert selected.status_code == 200, selected.text
        response = client.post(
            f"/api/projects/{project['id']}/runs", headers=headers, json={"stage": "extract"}
        )
        assert response.status_code == 201, response.text
        drain(client)
        body = dict(guard=guard(selected.json()), kind="source", bins=2000)
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(
                pool.map(lambda _: client.post(endpoint(f), headers=headers, json=body), range(2))
            )
        assert all(r.status_code == 202 for r in responses), [r.text for r in responses]
        assert len({r.json()["id"] for r in responses}) == 1
        run_id = responses[0].json()["id"]
        drain(client)
        result = client.get(endpoint(f) + "/" + run_id).json()
        assert result["status"] == "succeeded", result
        wave = result["waveform"]
        assert wave["sample_count"] == 48000 and wave["duration_ms"] == 1000
        assert wave["bin_count"] == 2000
        assert wave["clock"] == "source_selection_relative"
        assert wave["provenance"]["source_start_ms"] == 500
        assert wave["provenance"]["source_end_ms"] == 1500
        assert wave["bins"][0]["start_sample"] == 0
        assert wave["bins"][-1]["end_sample"] == 48000
    finally:
        if client:
            client.close()
            client.app.state.engine.dispose()
        if admin:
            admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))
            admin.close()

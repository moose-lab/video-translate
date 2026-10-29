"""Small API helpers shared by dubbing tests."""

import subprocess


def select_source(fixture, **changes):
    client, headers, p = fixture
    body = dict(
        revision=p["revision"], source_asset_id=p["source_asset_id"], audio_ordinal=0, start_ms=0
    )
    body.update(changes)
    return client.put(f"/api/projects/{p['id']}/source-selection", json=body, headers=headers)


def selected(fixture):
    response = select_source(fixture)
    assert response.status_code == 200, response.text
    return response.json()


def guard(selection, transcript=None):
    return {"selection_revision": selection["revision"], "transcript_revision": transcript}


def create_line(fixture, selection, text="Hello", transcript=None, start_ms=0, end_ms=500):
    client, headers, p = fixture
    response = client.post(
        f"/api/projects/{p['id']}/segments",
        headers=headers,
        json=guard(selection, transcript) | dict(text=text, start_ms=start_ms, end_ms=end_ms),
    )
    assert response.status_code == 201, response.text
    return response.json()


def make_track(c, h, base, tag, **kw):
    response = c.post(base + "/language-tracks", headers=h, json={"tag": tag} | kw)
    assert response.status_code == 201, response.text
    return response.json()


def make_probed_project(client_factory, register, tmp_path):
    client = client_factory()
    auth = register(client)
    headers = {"X-CSRF-Token": auth["csrf_token"]}
    project = client.post("/api/projects", json={"name": "Film"}, headers=headers).json()
    path = tmp_path / "source.mp4"
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
            "2",
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            "-shortest",
            str(path),
        ],
        check=True,
    )
    project = client.post(
        f"/api/projects/{project['id']}/source",
        headers=headers,
        files={"file": ("source.mp4", path.read_bytes(), "video/mp4")},
    ).json()["project"]
    run = client.post(
        f"/api/projects/{project['id']}/runs", headers=headers, json={"stage": "probe"}
    ).json()
    from videotranslate.execution.worker import Worker

    assert Worker(client.app.state.settings).run_once()
    assert client.get(f"/api/runs/{run['id']}").json()["status"] == "succeeded"
    return client, headers, project

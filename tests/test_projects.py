from concurrent.futures import ThreadPoolExecutor

import pytest


def test_project_crud_and_revision(client_factory, register):
    client = client_factory()
    auth = register(client)
    headers = {"X-CSRF-Token": auth["csrf_token"]}
    response = client.post("/api/projects", json={"name": "Film"}, headers=headers)
    assert response.status_code == 201
    project = response.json()
    assert project["name"] == "Film"
    assert project["revision"] == 1
    assert project["status"] == "draft"
    assert project["source_language"] == "auto"
    assert project["target_languages"] == ["en"]
    assert project["source_asset_id"] is None
    assert project["source_track_index"] == 0
    assert project["settings"] == {}
    project_id = project["id"]
    assert client.get("/api/projects").json() == {"items": [project], "total": 1}
    assert client.get(f"/api/projects/{project_id}").json() == project
    response = client.patch(
        f"/api/projects/{project_id}",
        headers=headers,
        json={
            "name": "New Film",
            "target_languages": ["es", "fr"],
            "source_language": "zh",
            "settings": {"auto_advance": False},
            "source_track_index": 2,
            "revision": 1,
        },
    )
    assert response.status_code == 200
    changed = response.json()
    assert changed["revision"] == 2
    assert changed["name"] == "New Film"
    assert changed["target_languages"] == ["es", "fr"]
    assert changed["source_track_index"] == 2
    assert changed["settings"] == {"auto_advance": False}
    assert client.delete(f"/api/projects/{project_id}", headers=headers).status_code == 204
    assert client.get(f"/api/projects/{project_id}").status_code == 404
    assert client.get("/api/projects").json() == {"items": [], "total": 0}
    assert client.delete(f"/api/projects/{project_id}", headers=headers).status_code == 404


def test_two_workspaces_cannot_list_read_write_or_delete_foreign_project(client_factory, register):
    owner = client_factory()
    auth = register(owner)
    project = owner.post(
        "/api/projects", json={"name": "Private"}, headers={"X-CSRF-Token": auth["csrf_token"]}
    ).json()
    other = client_factory(database_url=owner.app.state.settings.database_url.get_secret_value())
    other_auth = register(other, "other@example.com")
    assert other.get("/api/projects").json() == {"items": [], "total": 0}
    headers = {"X-CSRF-Token": other_auth["csrf_token"]}
    for project_id in (project["id"], "does-not-exist"):
        assert other.get(f"/api/projects/{project_id}").status_code == 404
        assert (
            other.patch(
                f"/api/projects/{project_id}", json={"name": "Hijack"}, headers=headers
            ).status_code
            == 404
        )
        assert other.delete(f"/api/projects/{project_id}", headers=headers).status_code == 404
    assert owner.get(f"/api/projects/{project['id']}").json()["name"] == "Private"


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("post", "/api/projects", {"name": "Film"}),
        ("patch", "/api/projects/unknown", {"name": "New"}),
        ("delete", "/api/projects/unknown", None),
    ],
)
def test_project_mutations_require_csrf(client_factory, register, method, path, body):
    client = client_factory()
    register(client)
    options = {"json": body} if body is not None else {}
    assert client.request(method, path, **options).status_code == 403
    assert (
        client.request(method, path, headers={"X-CSRF-Token": "wrong"}, **options).status_code
        == 403
    )


def test_concurrent_updates_with_same_revision_do_not_lose_writes(client_factory, register):
    client = client_factory()
    auth = register(client)
    headers = {"X-CSRF-Token": auth["csrf_token"]}
    project = client.post("/api/projects", headers=headers, json={"name": "Film"}).json()
    path = f"/api/projects/{project['id']}"
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(
            pool.map(
                lambda name: client.patch(
                    path, headers=headers, json={"name": name, "revision": 1}
                ),
                ["A", "B"],
            )
        )
    assert sorted(response.status_code for response in responses) == [200, 409]
    final = client.get(path).json()
    assert final["revision"] == 2
    assert final["name"] in {"A", "B"}
    conflict = next(response for response in responses if response.status_code == 409)
    assert conflict.json()["error"]["code"] == "REVISION_CONFLICT"


@pytest.mark.parametrize(
    "body",
    [
        {"name": "   "},
        {"target_languages": []},
        {"source_track_index": -1},
        {"status": "ready"},
        {"source_asset_id": "foreign"},
        {"settings": {"token": "secret"}},
    ],
)
def test_project_validation(client_factory, register, body):
    client = client_factory()
    auth = register(client)
    # Only operational settings are accepted; provider credentials belong to an encrypted vault.
    response = client.post(
        "/api/projects", headers={"X-CSRF-Token": auth["csrf_token"]}, json={"name": "Film", **body}
    )
    assert response.status_code == 422


def test_project_endpoints_require_login(client_factory):
    client = client_factory()
    assert client.get("/api/projects").status_code == 401
    assert client.get("/api/projects/unknown").status_code == 401
    assert client.post("/api/projects", json={"name": "Film"}).status_code == 401

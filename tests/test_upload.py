import hashlib
from io import BytesIO

import pytest
from sqlalchemy import event, select


def make_project(client, register):
    auth = register(client)
    headers = {"X-CSRF-Token": auth["csrf_token"]}
    response = client.post("/api/projects", json={"name": "Film"}, headers=headers)
    assert response.status_code == 201
    return response.json(), headers


def upload(client, project_id, headers, data, filename="source.mp4", mime="video/mp4"):
    return client.post(
        f"/api/projects/{project_id}/source",
        headers=headers,
        files={"file": (filename, data, mime)},
    )


def test_mp4_upload_exact_hash_bytes_revision_and_ranges(client_factory, register, tiny_mp4):
    client = client_factory()
    project, headers = make_project(client, register)
    response = upload(client, project["id"], headers, tiny_mp4, "../../源片.mp4")
    assert response.status_code == 201, response.text
    result = response.json()
    assert set(result) == {"project", "asset"}
    asset = result["asset"]
    assert asset["sha256"] == hashlib.sha256(tiny_mp4).hexdigest()
    assert asset["byte_size"] == len(tiny_mp4)
    assert asset["filename"] == "源片.mp4"
    assert asset["content_type"] == "video/mp4"
    assert asset["kind"] == "source_video"
    assert result["project"]["source_asset_id"] == asset["id"]
    assert result["project"]["status"] == "uploaded"
    assert result["project"]["revision"] == 2
    assert "storage_key" not in response.text
    assert "analysis" not in response.text
    listing = client.get(f"/api/projects/{project['id']}/assets")
    assert listing.json() == {"items": [asset], "total": 1}
    path = f"/api/assets/{asset['id']}/content"
    content = client.get(path)
    assert content.status_code == 200
    assert content.content == tiny_mp4
    assert content.headers["content-type"] == "video/mp4"
    assert content.headers["accept-ranges"] == "bytes"
    assert content.headers["content-disposition"].startswith("attachment;")
    assert "nosniff" in content.headers["x-content-type-options"]
    for value, start, end in [
        ("bytes=0-15", 0, 15),
        ("bytes=16-", 16, len(tiny_mp4) - 1),
        ("bytes=-12", len(tiny_mp4) - 12, len(tiny_mp4) - 1),
    ]:
        partial = client.get(path, headers={"Range": value})
        assert partial.status_code == 206
        assert partial.content == tiny_mp4[start : end + 1]
        assert partial.headers["content-range"] == f"bytes {start}-{end}/{len(tiny_mp4)}"
        assert int(partial.headers["content-length"]) == end - start + 1
    for value in ["bytes=999999-", "bytes=2-1", "bytes=0-1,4-5", "bad-range"]:
        invalid = client.get(path, headers={"Range": value})
        assert invalid.status_code == 416
        assert invalid.headers["content-range"] == f"bytes */{len(tiny_mp4)}"


def test_foreign_and_deleted_project_assets_are_inaccessible(client_factory, register, tiny_mp4):
    owner = client_factory()
    project, headers = make_project(owner, register)
    result = upload(owner, project["id"], headers, tiny_mp4)
    assert result.status_code == 201
    asset = result.json()["asset"]
    other = client_factory(database_url=owner.app.state.settings.database_url.get_secret_value())
    auth = register(other, "other@example.com")
    foreign_headers = {"X-CSRF-Token": auth["csrf_token"]}
    path = f"/api/assets/{asset['id']}/content"
    assert other.get(path).status_code == 404
    assert other.get(f"/api/projects/{project['id']}/assets").status_code == 404
    assert upload(other, project["id"], foreign_headers, tiny_mp4).status_code == 404
    owner.delete(f"/api/projects/{project['id']}", headers=headers)
    assert owner.get(path).status_code == 404
    assert owner.get(f"/api/projects/{project['id']}/assets").status_code == 404
    assert upload(owner, project["id"], headers, tiny_mp4).status_code == 404


@pytest.mark.parametrize(
    "filename,mime",
    [("bad.txt", "video/mp4"), ("bad.mp4", "text/html"), ("bad.mp4", "application/octet-stream")],
)
def test_upload_rejects_extension_and_declared_mime(
    client_factory, register, tiny_mp4, filename, mime
):
    client = client_factory()
    project, headers = make_project(client, register)
    response = upload(client, project["id"], headers, tiny_mp4, filename, mime)
    assert response.status_code == 415
    assert client.get(f"/api/projects/{project['id']}/assets").json()["items"] == []
    assert not [p for p in client.app.state.settings.local_storage_root.rglob("*") if p.is_file()]


def test_upload_is_not_claimed_as_decoded_or_analyzed(client_factory, register):
    client = client_factory()
    project, headers = make_project(client, register)
    response = upload(client, project["id"], headers, b"uploaded-but-not-media-probed")
    assert response.status_code == 201
    assert response.json()["project"]["status"] == "uploaded"


@pytest.mark.parametrize("size", [33, 100000])
def test_upload_size_limit_cleans_spools_and_objects(
    client_factory, register, size, tmp_path, monkeypatch
):
    monkeypatch.setattr("tempfile.tempdir", str(tmp_path))
    client = client_factory(upload_max_bytes=32)
    project, headers = make_project(client, register)
    response = upload(client, project["id"], headers, b"x" * size)
    assert response.status_code == 413
    assert client.get(f"/api/projects/{project['id']}/assets").json()["items"] == []
    assert not [p for p in client.app.state.settings.local_storage_root.rglob("*") if p.is_file()]


def test_empty_upload_rejected(client_factory, register):
    client = client_factory()
    project, headers = make_project(client, register)
    assert upload(client, project["id"], headers, b"").status_code == 422


def test_upload_requires_csrf_and_authentication(client_factory, register, tiny_mp4):
    client = client_factory()
    project, headers = make_project(client, register)
    assert upload(client, project["id"], {}, tiny_mp4).status_code == 403
    assert upload(client, project["id"], {"X-CSRF-Token": "wrong"}, tiny_mp4).status_code == 403
    client.post("/api/auth/logout", headers=headers)
    assert upload(client, project["id"], {}, tiny_mp4).status_code == 401
    assert client.get("/api/assets/missing/content").status_code == 401


def test_failed_database_persistence_removes_new_stored_object(client_factory, register, tiny_mp4):
    client = client_factory()
    project, headers = make_project(client, register)
    from videotranslate.models.core import Asset, Project

    def fail_asset_insert(_mapper, _connection, _target):
        raise RuntimeError("simulated persistence failure with private credentials")

    event.listen(Asset, "before_insert", fail_asset_insert)
    try:
        response = upload(client, project["id"], headers, tiny_mp4)
    finally:
        event.remove(Asset, "before_insert", fail_asset_insert)
    assert response.status_code == 500
    assert "private credentials" not in response.text
    assert not [p for p in client.app.state.settings.local_storage_root.rglob("*") if p.is_file()]
    with client.app.state.session_factory() as db:
        assert db.scalar(select(Asset)) is None
        stored_project = db.get(Project, project["id"])
        assert stored_project.source_asset_id is None
        assert stored_project.revision == 1


def test_storage_failure_cleans_partial_object_and_does_not_create_asset(
    client_factory, register, tiny_mp4, monkeypatch
):
    client = client_factory()
    project, headers = make_project(client, register)
    original_put = client.app.state.storage.put

    def broken_put(key, file, mime):
        original_put(key, BytesIO(b"partial"), mime)
        raise OSError("simulated interrupted upload")

    monkeypatch.setattr(client.app.state.storage, "put", broken_put)
    response = upload(client, project["id"], headers, tiny_mp4)
    assert response.status_code == 503
    assert not [p for p in client.app.state.settings.local_storage_root.rglob("*") if p.is_file()]
    assert client.get(f"/api/projects/{project['id']}/assets").json()["total"] == 0


@pytest.mark.parametrize("mode", ["missing", "wrong-field", "multiple", "json", "malformed"])
def test_malformed_upload_is_a_safe_validation_error(client_factory, register, mode):
    client = client_factory()
    project, headers = make_project(client, register)
    path = f"/api/projects/{project['id']}/source"
    options = {}
    if mode == "wrong-field":
        options = {"files": {"other": ("x.mp4", b"x", "video/mp4")}}
    elif mode == "multiple":
        options = {
            "files": [
                ("file", ("a.mp4", b"x", "video/mp4")),
                ("file", ("b.mp4", b"x", "video/mp4")),
            ]
        }
    elif mode == "json":
        options = {"json": {"secret": "never-return-this"}}
    elif mode == "malformed":
        options = {"content": b"not-a-multipart-body"}
        headers = {**headers, "Content-Type": "multipart/form-data; boundary=xyz"}
    response = client.post(path, headers=headers, **options)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_UPLOAD"
    assert "never-return-this" not in response.text


def test_failure_after_prior_upload_preserves_approved_source(client_factory, register, tiny_mp4):
    client = client_factory()
    project, headers = make_project(client, register)
    first = upload(client, project["id"], headers, tiny_mp4)
    assert first.status_code == 201
    from videotranslate.models.core import Asset

    def fail_insert(_mapper, _connection, _target):
        raise RuntimeError("replacement failed")

    event.listen(Asset, "before_insert", fail_insert)
    try:
        assert upload(client, project["id"], headers, tiny_mp4).status_code == 500
    finally:
        event.remove(Asset, "before_insert", fail_insert)
    previous = first.json()
    assert client.get(f"/api/projects/{project['id']}").json() == previous["project"]
    assert client.get(f"/api/assets/{previous['asset']['id']}/content").content == tiny_mp4
    assert (
        len([p for p in client.app.state.settings.local_storage_root.rglob("*") if p.is_file()])
        == 1
    )


def test_chunked_body_limit_closes_already_open_spools(client_factory, register, monkeypatch):
    import asyncio
    import tempfile

    import httpx
    from starlette.formparsers import MultiPartParser

    client = client_factory(upload_max_bytes=32)
    project, headers = make_project(client, register)
    spools = []
    original_spool = tempfile.SpooledTemporaryFile

    def tracked_spool(*args, **kwargs):
        spool = original_spool(*args, **kwargs)
        spools.append(spool)
        return spool

    monkeypatch.setattr("starlette.formparsers.SpooledTemporaryFile", tracked_spool)
    monkeypatch.setattr(MultiPartParser, "spool_max_size", 8)

    async def body():
        yield (
            b'--test-boundary\r\nContent-Disposition: form-data; name="file"; '
            b'filename="source.mp4"\r\nContent-Type: video/mp4\r\n\r\n' + b"x" * 32
        )
        yield b"x" * 70000
        yield b"\r\n--test-boundary--\r\n"

    async def post():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=client.app), base_url="http://testserver"
        ) as streamed:
            return await streamed.post(
                f"/api/projects/{project['id']}/source",
                content=body(),
                headers={
                    **headers,
                    "Content-Type": "multipart/form-data; boundary=test-boundary",
                    "Cookie": f"vt_session={client.cookies.get('vt_session')}; "
                    f"vt_csrf={client.cookies.get('vt_csrf')}",
                },
            )

    response = asyncio.run(post())
    assert response.status_code == 413
    assert spools and all(spool.closed for spool in spools)
    assert any(spool._rolled for spool in spools)  # Actual filesystem-backed spool was exercised.


def test_download_stream_failure_does_not_leak_storage_details(
    client_factory, register, tiny_mp4, monkeypatch
):
    from fastapi.testclient import TestClient

    client = client_factory()
    project, headers = make_project(client, register)
    response = upload(client, project["id"], headers, tiny_mp4)
    assert response.status_code == 201
    asset_id = response.json()["asset"]["id"]

    class BrokenRead(BytesIO):
        def read(self, *args):
            raise RuntimeError("private-storage-key-or-signed-url-never-log")

    monkeypatch.setattr(client.app.state.storage, "open", lambda *args, **kwargs: BrokenRead())
    with TestClient(client.app, raise_server_exceptions=True) as strict:
        strict.cookies.update(client.cookies)
        with pytest.raises(RuntimeError, match="Media stream interrupted") as captured:
            strict.get(f"/api/assets/{asset_id}/content")
    assert "private-storage" not in str(captured.value)


def test_asset_collection_has_default_bound_and_unpaged_total(paginated_collections):
    fixture = paginated_collections
    response = fixture["owner"].get(f"/api/projects/{fixture['project_id']}/assets")
    assert response.status_code == 200
    assert response.json()["total"] == 150
    assert [item["id"] for item in response.json()["items"]] == fixture["assets"][:50]


@pytest.mark.parametrize("limit,offset", [(10, 0), (10, 10), (10, 145), (200, 0), (10, 150)])
def test_asset_pages_are_stable_and_keep_project_workspace_scope(
    paginated_collections, limit, offset
):
    fixture = paginated_collections
    path = f"/api/projects/{fixture['project_id']}/assets?limit={limit}&offset={offset}"
    response = fixture["owner"].get(path)
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 150
    assert [item["id"] for item in body["items"]] == fixture["assets"][offset : offset + limit]
    assert fixture["owner"].get(path).json() == body
    assert fixture["other"].get(path).status_code == 404
    for project_id in (fixture["deleted_project_id"], fixture["foreign_project_id"]):
        assert (
            fixture["owner"]
            .get(f"/api/projects/{project_id}/assets?limit={limit}&offset={offset}")
            .status_code
            == 404
        )


@pytest.mark.parametrize(
    "query", ["limit=0", "limit=-1", "limit=201", "offset=-1", "limit=bad", "offset=1.5"]
)
def test_asset_pagination_rejects_invalid_bounds(client_factory, register, query):
    client = client_factory()
    project, _ = make_project(client, register)
    assert client.get(f"/api/projects/{project['id']}/assets?{query}").status_code == 422

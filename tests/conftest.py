import importlib.util
import itertools
import subprocess

import pytest
from fastapi.testclient import TestClient

from videotranslate.config import Settings


@pytest.fixture
def client_factory(tmp_path):
    clients = []
    counter = itertools.count()

    def create(**overrides):
        assert importlib.util.find_spec("videotranslate.app") is not None, "App factory missing"
        from videotranslate.app import create_app

        index = next(counter)
        values = dict(
            environment="test",
            database_url=f"sqlite:///{tmp_path}/db-{index}.db",
            storage_backend="local",
            local_storage_root=tmp_path / f"media-{index}",
        )
        values.update(overrides)
        client = TestClient(create_app(Settings(**values)), raise_server_exceptions=False)
        clients.append(client)
        return client

    yield create
    for client in clients:
        client.close()
        client.app.state.engine.dispose()


@pytest.fixture
def register():
    def register_account(client, email="creator@example.com"):
        response = client.post(
            "/api/auth/register",
            json={"email": email, "password": "correct-horse-123", "name": "Creator"},
        )
        assert response.status_code == 201, response.text
        return response.json()

    return register_account


@pytest.fixture(scope="session")
def tiny_mp4(tmp_path_factory):
    path = tmp_path_factory.mktemp("media-fixture") / "tiny.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=32x32:r=5",
            "-t",
            "0.4",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(path),
        ],
        check=True,
    )
    return path.read_bytes()


@pytest.fixture
def paginated_collections(client_factory, register):
    """Real persisted collections with timestamp ties and foreign/deleted neighbors."""
    from datetime import timedelta
    from uuid import UUID

    from videotranslate.models.core import Asset, Project, utcnow

    owner = client_factory()
    auth = register(owner)
    other = client_factory(database_url=owner.app.state.settings.database_url.get_secret_value())
    other_auth = register(other, "other@example.com")
    workspace_id, foreign_workspace_id = auth["workspace"]["id"], other_auth["workspace"]["id"]
    now = utcnow()

    def project(index, workspace, *, deleted=False):
        return Project(
            id=str(UUID(int=index)),
            workspace_id=workspace,
            name=f"Film {index}",
            created_at=now + timedelta(seconds=index % 7),
            deleted_at=now if deleted else None,
        )

    projects = [project(i, workspace_id) for i in range(1, 151)]
    deleted = [project(i, workspace_id, deleted=True) for i in range(201, 231)]
    foreign = [project(i, foreign_workspace_id) for i in range(301, 381)]
    project_id = projects[0].id

    def asset(index, workspace, parent):
        return Asset(
            id=str(UUID(int=1000 + index)),
            workspace_id=workspace,
            project_id=parent,
            filename=f"{index}.mp4",
            content_type="video/mp4",
            byte_size=1,
            sha256="0" * 64,
            kind="source_video",
            storage_key=f"test/{index}",
            created_at=now + timedelta(seconds=index % 7),
        )

    assets = [asset(i, workspace_id, project_id) for i in range(1, 151)]
    excluded_assets = (
        [asset(i, workspace_id, projects[1].id) for i in range(201, 241)]
        + [asset(i, workspace_id, deleted[0].id) for i in range(301, 306)]
        + [asset(i, foreign_workspace_id, foreign[0].id) for i in range(401, 421)]
        + [asset(i, foreign_workspace_id, project_id) for i in range(501, 504)]
    )
    with owner.app.state.session_factory.begin() as db:
        db.add_all(list(reversed(projects)) + deleted + foreign)
        db.flush()
        db.add_all(list(reversed(assets)) + excluded_assets)

    def ordered_ids(rows):
        return [
            row.id for row in sorted(rows, key=lambda row: (-row.created_at.timestamp(), row.id))
        ]

    return {
        "owner": owner,
        "other": other,
        "projects": ordered_ids(projects),
        "assets": ordered_ids(assets),
        "project_id": project_id,
        "deleted_project_id": deleted[0].id,
        "foreign_project_id": foreign[0].id,
    }

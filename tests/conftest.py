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

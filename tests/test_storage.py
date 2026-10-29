import importlib.util
from io import BytesIO

import pytest


def storage_types():
    assert importlib.util.find_spec("videotranslate.storage") is not None, (
        "Storage interface missing"
    )
    from videotranslate.storage import LocalStorage, S3Storage

    return LocalStorage, S3Storage


def test_local_storage_round_trip_range_and_delete(tmp_path):
    LocalStorage, _ = storage_types()
    storage = LocalStorage(tmp_path / "private")
    storage.put("work/project/object.mp4", BytesIO(b"0123456789"), "video/mp4")
    with storage.open("work/project/object.mp4") as stream:
        assert stream.read() == b"0123456789"
    with storage.open("work/project/object.mp4", start=2, end=4) as stream:
        assert stream.read() == b"234"
    assert (tmp_path / "private/work/project/object.mp4").stat().st_mode & 0o077 == 0
    storage.delete("work/project/object.mp4")
    storage.delete("work/project/object.mp4")
    with pytest.raises(FileNotFoundError):
        storage.open("work/project/object.mp4")


@pytest.mark.parametrize(
    "key",
    [
        "/etc/passwd",
        "../secret",
        "a/../../secret",
        "",
        ".",
        "a//b",
        "a/./b",
        "a\\b",
        "C:/secret",
        "a\x00b",
    ],
)
def test_local_and_s3_reject_unsafe_keys(tmp_path, key):
    LocalStorage, S3Storage = storage_types()
    for storage in (LocalStorage(tmp_path), S3Storage("bucket", client=FakeS3())):
        for action in (
            lambda storage=storage: storage.put(key, BytesIO(b"x"), "video/mp4"),
            lambda storage=storage: storage.open(key),
            lambda storage=storage: storage.delete(key),
        ):
            with pytest.raises(ValueError):
                action()


def test_local_storage_rejects_symlink_escape(tmp_path):
    LocalStorage, _ = storage_types()
    root, outside = tmp_path / "root", tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (root / "escape").symlink_to(outside, target_is_directory=True)
    storage = LocalStorage(root)
    with pytest.raises(ValueError):
        storage.put("escape/file.mp4", BytesIO(b"x"), "video/mp4")
    assert not list(outside.iterdir())


def test_local_partial_write_is_removed(tmp_path):
    LocalStorage, _ = storage_types()
    storage = LocalStorage(tmp_path)

    class BrokenStream(BytesIO):
        def read(self, *args):
            raise OSError("simulated read failure")

    with pytest.raises(OSError):
        storage.put("a/object.mp4", BrokenStream(b"bad"), "video/mp4")
    assert not [p for p in tmp_path.rglob("*") if p.is_file()]


class FakeS3:
    """Isolated S3 contract fake. No cloud connectivity or privacy verification claimed."""

    def __init__(self):
        self.calls = []
        self.data = b""

    def put_object(self, **kwargs):
        self.calls.append(("put", kwargs))
        self.data = kwargs["Body"].read()

    def get_object(self, **kwargs):
        self.calls.append(("get", kwargs))
        data = self.data
        if "Range" in kwargs:
            start, end = kwargs["Range"][6:].split("-")
            data = data[int(start) : int(end) + 1 if end else None]
        return {"Body": BytesIO(data)}

    def delete_object(self, **kwargs):
        self.calls.append(("delete", kwargs))


def test_s3_contract_uses_private_parameters_and_ranges():
    _, S3Storage = storage_types()
    fake = FakeS3()
    storage = S3Storage("private-vt", client=fake)
    storage.put("w/p/object.mp4", BytesIO(b"0123456789"), "video/mp4")
    put = fake.calls[-1][1]
    assert put["Bucket"] == "private-vt"
    assert put["Key"] == "w/p/object.mp4"
    assert put["ContentType"] == "video/mp4"
    assert "ACL" not in put
    with storage.open("w/p/object.mp4", 2, 5) as stream:
        assert stream.read() == b"2345"
    assert fake.calls[-1][1]["Range"] == "bytes=2-5"
    storage.delete("w/p/object.mp4")
    assert fake.calls[-1] == ("delete", {"Bucket": "private-vt", "Key": "w/p/object.mp4"})

"""Materialize immutable stored inputs with bounded, cancellable reads."""

from .contracts import FailureCode, StageFailure


def materialize(context, asset, destination, *, max_bytes):
    import hashlib

    digest = hashlib.sha256()
    size = 0
    with context.storage.open(asset.storage_key) as source, destination.open("wb") as output:
        while chunk := source.read(1024 * 1024):
            context.check_active()
            size += len(chunk)
            if size > max_bytes:
                raise StageFailure(FailureCode.MEDIA_LIMIT)
            digest.update(chunk)
            output.write(chunk)
    if size != asset.byte_size or digest.hexdigest() != asset.sha256:
        raise StageFailure(FailureCode.INVALID_MEDIA)

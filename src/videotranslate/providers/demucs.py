"""Validate real Demucs two-stem outputs; paths stay remote."""

from dataclasses import dataclass


def normalize_stems(value):
    if (
        not isinstance(value, list)
        or len(value) != 2
        or any(not isinstance(item, dict) for item in value)
    ):
        raise ValueError("Provider returned invalid stems")
    paths = [item.get("path") for item in value]
    if (
        any(
            not isinstance(path, str)
            or not path
            or path.lower().startswith(("file:", "http:", "https:"))
            for path in paths
        )
        or paths[0] == paths[1]
    ):
        raise ValueError("Provider returned invalid stems")
    return {"vocals": value[0], "instrumental": value[1]}


@dataclass(frozen=True)
class PreparedSeparation:
    host: str
    prefix: str
    reference: dict


def prepare_separation(http, *, audio, space_id="kajise/Demucs_v4-FT_2s", model="htdemucs_ft"):
    """Schema and generic-name upload only; there is no named inference call here."""
    import json

    from .gradio import GradioClient, discover_prefix, resolve_space, validate_endpoint_schema

    if model != "htdemucs_ft":
        raise ValueError("Unsupported Demucs model")
    host = resolve_space(http, space_id)
    prefix = discover_prefix(http, host, "/predict")
    schema = json.loads(http.get(host + prefix + "/info", max_bytes=2 * 1024 * 1024))
    validate_endpoint_schema(schema, "demucs")
    reference = GradioClient(http, host, prefix).upload("audio.wav", audio, "audio/wav")
    return PreparedSeparation(host, prefix, reference)


def submit_prepared(http, prepared):
    from .gradio import GradioClient

    return GradioClient(http, prepared.host, prepared.prefix).submit(
        "predict", [prepared.reference]
    )


def submit_separation(
    http, *, audio, filename, space_id="kajise/Demucs_v4-FT_2s", model="htdemucs_ft"
):
    from .contracts import RemoteResult

    prepared = prepare_separation(http, audio=audio, space_id=space_id, model=model)
    event_id = submit_prepared(http, prepared)
    return RemoteResult(
        status="pending",
        remote_id=event_id,
        payload={"host": prepared.host, "prefix": prepared.prefix},
    )


def poll_separation(http, handle):
    from .contracts import RemoteResult
    from .gradio import GradioClient

    if not handle.remote_id or handle.status != "pending":
        raise ValueError("A pending provider event ID is required")
    client = GradioClient(http, handle.payload["host"], handle.payload["prefix"])
    payload = client.poll("predict", handle.remote_id)
    if payload is None:
        return handle
    stems = normalize_stems(payload)
    vocals = client.download(stems["vocals"])
    try:
        instrumental = client.download(stems["instrumental"])
    except Exception:
        vocals.unlink(missing_ok=True)
        raise
    return RemoteResult(
        status="succeeded",
        remote_id=handle.remote_id,
        payload={"vocals_path": str(vocals), "instrumental_path": str(instrumental)},
    )

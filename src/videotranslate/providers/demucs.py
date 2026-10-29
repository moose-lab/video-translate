"""Explicit remote Demucs contracts; legacy operations retain two-stem defaults."""

from dataclasses import dataclass

MULTISTEM_SPACE = "teamup-tech/Demucs"
MULTISTEM_HOST = "https://teamup-tech-demucs.hf.space"
MULTISTEM_REVISION = "541b5b5bdee7e1eb6163d6f4e064e9e24f33c40c"


def output_mapping(adapter="demucs"):
    if adapter == "demucs":
        return ("vocals", "instrumental")
    if adapter == "demucs_multistem":
        return ("drums", "bass", "vocals", "other")
    raise ValueError("Unsupported Demucs profile")


def normalize_stems(value, adapter="demucs"):
    mapping = output_mapping(adapter)
    if (
        not isinstance(value, list)
        or len(value) != len(mapping)
        or any(not isinstance(item, dict) for item in value)
    ):
        raise ValueError("Provider returned invalid stems")
    paths = [item.get("path") for item in value]
    if any(
        not isinstance(path, str)
        or not path
        or path.lower().startswith(("file:", "http:", "https:"))
        or any(ord(c) < 32 or ord(c) == 127 for c in path)
        for path in paths
    ) or len(set(paths)) != len(paths):
        raise ValueError("Provider returned invalid stems")
    return dict(zip(mapping, value, strict=True))


@dataclass(frozen=True)
class PreparedSeparation:
    host: str
    prefix: str
    reference: dict
    adapter: str = "demucs"
    api_name: str = "predict"
    model: str = "htdemucs_ft"
    output_mapping: tuple[str, ...] = ("vocals", "instrumental")


def prepare_separation(
    http, *, audio, space_id="kajise/Demucs_v4-FT_2s", model="htdemucs_ft", adapter="demucs"
):
    """Schema and generic-name upload only; there is no named inference call here."""
    import json

    from .gradio import GradioClient, discover_prefix, resolve_space, validate_endpoint_schema
    from .settings import preset_supported

    mapping = output_mapping(adapter)
    if not preset_supported(adapter, model, space_id, None):
        raise ValueError("Unsupported Demucs configuration")
    host = resolve_space(
        http,
        space_id,
        expected_revision=MULTISTEM_REVISION if adapter == "demucs_multistem" else None,
    )
    if adapter == "demucs_multistem" and host != MULTISTEM_HOST:
        raise ValueError("Unsupported Demucs host")
    api_name = "process" if adapter == "demucs_multistem" else "predict"
    prefix = discover_prefix(http, host, "/" + api_name)
    if adapter == "demucs_multistem" and prefix != "/gradio_api":
        raise ValueError("Unsupported Demucs API prefix")
    schema = json.loads(http.get(host + prefix + "/info", max_bytes=2 * 1024 * 1024))
    validate_endpoint_schema(schema, adapter)
    reference = GradioClient(http, host, prefix).upload("audio.wav", audio, "audio/wav")
    return PreparedSeparation(host, prefix, reference, adapter, api_name, model, mapping)


def submit_prepared(http, prepared):
    from .gradio import GradioClient

    return GradioClient(http, prepared.host, prepared.prefix).submit(
        prepared.api_name,
        [prepared.reference, prepared.model]
        if prepared.adapter == "demucs_multistem"
        else [prepared.reference],
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

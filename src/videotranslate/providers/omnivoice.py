"""OmniVoice request and result validation; no local inference."""

from ..languages.catalog import key, resolve
from .settings import validate_controls


def model_name_from_enum(language, enum):
    row = resolve(language)
    matches = [
        candidate
        for candidate in enum
        if isinstance(candidate, str) and key(candidate) == key(row["model_name"])
    ]
    if len(matches) != 1:
        raise ValueError("Language unavailable or ambiguous in provider schema")
    return matches[0]


def clone_arguments(
    text, language, reference, reference_text, *, language_enum=None, controls=None
):
    language_row = resolve(language)
    if (
        language_row["is_auto"]
        or not text
        or not isinstance(reference, dict)
        or not isinstance(reference.get("path"), str)
        or not reference.get("path")
        or reference["path"].lower().startswith(("file:", "http:", "https:"))
        or any(ord(char) < 32 for char in reference["path"])
    ):
        raise ValueError("Explicit language, text, and uploaded reference are required")
    controls = controls or {}
    validate_controls("omnivoice", controls)
    return [
        text,
        model_name_from_enum(language, language_enum)
        if language_enum is not None
        else language_row["model_name"],
        reference,
        reference_text,
        "",
        controls.get("ns", 32),
        controls.get("gs", 2.0),
        controls.get("dn", True),
        controls.get("sp", 1.0),
        controls.get("du"),
        controls.get("pp", True),
        controls.get("po", True),
    ]


def normalize_result(value):
    if not isinstance(value, list) or len(value) != 2 or not isinstance(value[0], dict):
        raise ValueError("Provider returned no audio")
    audio, status = value
    path = audio.get("path")
    if (
        not isinstance(path, str)
        or not path
        or path.lower().startswith(("file:", "http:", "https:"))
    ):
        raise ValueError("Provider returned invalid audio")
    if not isinstance(status, str) or status.strip() != "Done.":
        raise ValueError("Provider did not report success")
    return {"audio": audio, "status": status}


def submit_clone(
    http,
    *,
    text,
    language,
    reference_audio,
    filename,
    reference_text,
    space_id="k2-fsa/OmniVoice",
    model="OmniVoice",
    controls=None,
    hf_token=None,
):
    import json

    from .contracts import RemoteResult
    from .gradio import GradioClient, discover_prefix, resolve_space, validate_endpoint_schema

    if model != "OmniVoice":
        raise ValueError("Unsupported OmniVoice model")
    host = resolve_space(http, space_id)
    prefix = discover_prefix(http, host, "/_clone_fn")
    schema = json.loads(http.get(host + prefix + "/info", max_bytes=2 * 1024 * 1024))
    validate_endpoint_schema(schema, "omnivoice")
    try:
        enum = schema["named_endpoints"]["/_clone_fn"]["parameters"][1]["type"]["enum"]
        if not isinstance(enum, list):
            raise ValueError()
        model_name_from_enum(language, enum)
    except (KeyError, TypeError, ValueError):
        raise ValueError("Language unavailable in provider schema") from None
    clone_arguments(
        text,
        language,
        {"path": "remote-upload-placeholder"},
        reference_text,
        language_enum=enum,
        controls=controls,
    )
    client = GradioClient(http, host, prefix, hf_token=hf_token)
    reference = client.upload(filename, reference_audio, "audio/wav")
    args = clone_arguments(
        text, language, reference, reference_text, language_enum=enum, controls=controls
    )
    event_id = client.submit("_clone_fn", args)
    return RemoteResult(
        status="pending", remote_id=event_id, payload={"host": host, "prefix": prefix}
    )


def poll_clone(http, handle, *, hf_token=None):
    from .contracts import RemoteResult
    from .gradio import GradioClient

    if not handle.remote_id or handle.status != "pending":
        raise ValueError("A pending provider event ID is required")
    client = GradioClient(http, handle.payload["host"], handle.payload["prefix"], hf_token=hf_token)
    payload = client.poll("_clone_fn", handle.remote_id)
    if payload is None:
        return handle
    result = normalize_result(payload)
    local_path = client.download(result["audio"])
    return RemoteResult(
        status="succeeded",
        remote_id=handle.remote_id,
        payload={"local_audio_path": str(local_path)},
    )

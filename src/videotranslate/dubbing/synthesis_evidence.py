"""Pure immutable preparation and measured-audio evidence checks; no current heads or network."""

from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import Field

from ..execution.inputs import fingerprint
from ..execution.prepared import bounded
from ..providers.gradio import parse_submission
from ..providers.network import validate_url
from ..providers.omnivoice import clone_arguments, model_name_from_enum, normalize_result
from .contracts import ID, Fingerprint, Strict

MAX_BYTES = 64 * 1024 * 1024


class AudioEvidence(Strict):
    duration_ms: Annotated[int, Field(ge=1, le=600080)]
    sample_rate: Annotated[int, Field(ge=8000, le=192000)]
    channels: Annotated[int, Field(ge=1, le=8)]
    byte_size: Annotated[int, Field(ge=1, le=MAX_BYTES)]
    sha256: Fingerprint
    codec: Annotated[str, Field(min_length=1, max_length=40, pattern=r"^[a-z0-9_]+$")]
    container: Literal["wav", "mp3", "ogg", "flac", "mov,mp4,m4a,3gp,3g2,mj2", "matroska,webm"]


class OperationProof(Strict):
    provider: Literal["omnivoice"]
    model: Literal["OmniVoice"]
    connection_revision: Annotated[int, Field(ge=0)]
    binding_sha256: Fingerprint


class DecodeProof(Strict):
    version: Annotated[int, Field(ge=1, le=1)]
    full_decode: bool
    raw_metadata: AudioEvidence
    operation: OperationProof


class AliasBinding(Strict):
    line_id: ID
    operation_id: ID
    generation: Fingerprint
    input_fingerprint: Fingerprint
    prepared_sha256: Fingerprint
    provenance_sha256: Fingerprint


class PreparedClone(Strict):
    host: Annotated[str, Field(min_length=1, max_length=300)]
    prefix: Literal["", "/gradio_api"]
    api_name: Literal["_clone_fn"]
    metadata_revision: Annotated[str, Field(min_length=1, max_length=200)]
    schema_sha256: Fingerprint
    language_enum: Annotated[
        list[Annotated[str, Field(min_length=1, max_length=200)]],
        Field(min_length=1, max_length=2000),
    ]
    model_language: Annotated[str, Field(min_length=1, max_length=200)]
    args: Annotated[list, Field(min_length=12, max_length=12)]


def validate_operation(operation, inputs, *, producing):
    """Real submissions and local cache aliases have distinct, exact private request shapes."""
    if (
        operation.provider != "omnivoice"
        or operation.provider != inputs["config"]["adapter"]
        or operation.model != inputs["config"]["model"]
        or operation.model != "OmniVoice"
        or type(operation.connection_revision) is not int
        or operation.connection_revision != inputs["connection_revision"]
        or fingerprint(operation.request_payload.get("input")) != fingerprint(inputs)
    ):
        raise ValueError("Inconsistent immutable synthesis operation")
    if not producing:
        if (
            set(operation.request_payload) not in ({"input"}, {"input", "reuse"})
            or ("reuse" not in operation.request_payload and operation.phase != "prepared")
            or operation.host
            or operation.prefix
            or operation.remote_id is not None
            or operation.terminal_payload is not None
        ):
            raise ValueError("Invalid synthesis reuse alias")
        if "reuse" in operation.request_payload:
            AliasBinding.model_validate(operation.request_payload["reuse"])
        return None
    if set(operation.request_payload) != {"input", "prepared"}:
        raise ValueError("Missing immutable synthesis preparation")
    prepared = PreparedClone.model_validate(operation.request_payload["prepared"]).model_dump()
    host = prepared["host"]
    validate_url(host)
    parts = urlsplit(host)
    reference = prepared["args"][2]
    if (
        parts.path not in {"", "/"}
        or not (parts.hostname or "").endswith(".hf.space")
        or operation.host != host
        or operation.prefix != prepared["prefix"]
        or (inputs["config"].get("endpoint") and inputs["config"]["endpoint"].rstrip("/") != host)
        or prepared["model_language"]
        != model_name_from_enum(inputs["target"], prepared["language_enum"])
        or not isinstance(reference, dict)
        or set(reference) != {"path", "orig_name", "mime_type", "meta"}
        or reference["orig_name"] != "reference.wav"
        or reference["mime_type"] != "audio/wav"
        or reference["meta"] != {"_type": "gradio.FileData"}
        or fingerprint(prepared["args"])
        != fingerprint(
            clone_arguments(
                inputs["text"],
                inputs["target"],
                reference,
                inputs["reference_text"],
                language_enum=prepared["language_enum"],
                controls=inputs["controls"],
            )
        )
    ):
        raise ValueError("Invalid immutable synthesis preparation")
    return prepared


def validate_terminal(operation):
    parse_submission({"event_id": operation.remote_id})
    terminal = operation.terminal_payload
    bounded(terminal)
    if set(terminal) != {"audio", "status"}:
        raise ValueError("Invalid saved synthesis terminal result")
    normalize_result([terminal["audio"], terminal["status"]])
    path = terminal["audio"]["path"]
    if len(path) > 10000 or any(ord(char) < 32 for char in path):
        raise ValueError("Invalid saved synthesis file")


def operation_proof(operation):
    """Minimal digest binds the actual saved named request, receipt and terminal FileData."""
    fields = (
        "id",
        "run_id",
        "project_id",
        "workspace_id",
        "generation",
        "input_fingerprint",
        "host",
        "prefix",
        "request_payload",
        "remote_id",
        "terminal_payload",
    )
    return {
        "provider": operation.provider,
        "model": operation.model,
        "connection_revision": operation.connection_revision,
        "binding_sha256": fingerprint({key: getattr(operation, key) for key in fields}),
    }


def validate_audio_pair(raw_metadata, metadata):
    raw = AudioEvidence.model_validate(raw_metadata).model_dump()
    natural = AudioEvidence.model_validate(metadata).model_dump()
    if (
        raw["duration_ms"] > 600000
        or raw["codec"] == "unknown"
        or natural["container"] != "wav"
        or natural["codec"] != "pcm_s16le"
    ):
        raise ValueError("Invalid measured synthesis audio")
    if raw["container"] == "wav" and raw["codec"] == "pcm_s16le":
        if raw != natural:
            raise ValueError("Unchanged PCM WAV evidence differs")
    elif (
        natural["sample_rate"] != 48000
        or natural["channels"] != min(raw["channels"], 2)
        or abs(natural["duration_ms"] - raw["duration_ms"]) > 80
        or natural["sha256"] == raw["sha256"]
    ):
        raise ValueError("Inconsistent normalized synthesis measurements")
    return raw, natural


def measured_provenance(operation, raw_metadata, metadata):
    raw, _ = validate_audio_pair(raw_metadata, metadata)
    return {
        "version": 1,
        "full_decode": True,
        "raw_metadata": raw,
        "operation": operation_proof(operation),
    }

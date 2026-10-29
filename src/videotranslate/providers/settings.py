from sqlalchemy import select

from ..models.providers import ProviderConnectionRevision

SLOTS = ("separation", "transcription", "translation", "synthesis", "verification")


def resolve_revision(db, workspace_id, slot, revision):
    row = db.scalar(
        select(ProviderConnectionRevision).where(
            ProviderConnectionRevision.workspace_id == workspace_id,
            ProviderConnectionRevision.slot == slot,
            ProviderConnectionRevision.revision == revision,
        )
    )
    if not row:
        raise LookupError("Connection revision unavailable")
    return row.settings


def validate_controls(adapter, controls):
    import math

    supported = {
        "omnivoice": {"ns", "gs", "dn", "sp", "du", "pp", "po"},
        "nvidia_stream": {"max_speakers"},
        "demucs": set(),
        "demucs_multistem": set(),
        "hf_router": set(),
        "hf_asr": set(),
        "openai_compatible": set(),
    }
    if (
        adapter not in supported
        or not isinstance(controls, dict)
        or set(controls) - supported[adapter]
    ):
        raise ValueError("Unsupported provider controls")
    for name, value in controls.items():
        valid = False
        if name in {"dn", "pp", "po"}:
            valid = isinstance(value, bool)
        elif name in {"ns", "max_speakers"}:
            low, high = (4, 64) if name == "ns" else (1, 8)
            valid = isinstance(value, int) and not isinstance(value, bool) and low <= value <= high
        elif name in {"gs", "sp", "du"}:
            if name == "du" and value is None:
                valid = True
            elif (
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                and math.isfinite(value)
            ):
                low, high = {"gs": (0, 4), "sp": (0.5, 1.5), "du": (0.01, 10000)}[name]
                valid = low <= value <= high
        if not valid:
            raise ValueError("Invalid provider controls")


def capability_contract(slot, adapter, schema=None, model=None):
    from dataclasses import asdict

    from ..languages.catalog import resolve
    from .contracts import ProviderCapabilities

    supported = []
    if adapter == "nvidia_stream":
        supported = ["en", "en-US", "en-GB"]
    elif adapter == "omnivoice" and schema is not None:
        try:
            enum = schema["named_endpoints"]["/_clone_fn"]["parameters"][1]["type"]["enum"]
            if not isinstance(enum, list):
                raise ValueError()
            for name in enum:
                try:
                    item = resolve(name)
                    if not item["is_auto"] and item["code"] not in supported:
                        supported.append(item["code"])
                except (ValueError, TypeError):
                    continue
        except (KeyError, TypeError, ValueError):
            raise ValueError("Provider language enum unavailable") from None
    controls = {
        "omnivoice": ("ns", "gs", "dn", "sp", "du", "pp", "po"),
        "nvidia_stream": ("max_speakers",),
    }.get(adapter, ())
    capability = ProviderCapabilities(
        stage=slot,
        language_support="unsupported" if adapter == "nvidia_stream" else "unknown",
        supported_languages=tuple(supported),
        resumable=adapter in {"omnivoice", "demucs", "demucs_multistem"},
        cancel_supported=False,
        max_duration_seconds=120 if adapter == "nvidia_stream" else None,
        controls=controls,
    )
    result = asdict(capability)
    if adapter == "hf_asr":
        from .asr_languages import WHISPER_LANGUAGES, WHISPER_REVISION

        known = model == "openai/whisper-large-v3"
        result.update(
            {
                "supported_languages": list(WHISPER_LANGUAGES) if known else [],
                "language_support": "unsupported" if known else "unknown",
                "auto_detection": known,
                "speaker_labels": False,
                "detected_language_guaranteed": False,
                "model_declaration_revision": WHISPER_REVISION if known else None,
                "task_route": "hf-inference/models/{model}",
            }
        )
    if adapter == "demucs_multistem":
        from .demucs import MULTISTEM_REVISION, output_mapping

        result.update(
            {
                "outputs": list(output_mapping(adapter)),
                "instrumental_sources": ["drums", "bass", "other"],
                "published_outputs": ["vocals", "instrumental"],
                "api_name": "process",
                "model": "htdemucs",
                "space_revision": MULTISTEM_REVISION,
                "credential_mode": "public_demo",
            }
        )
    return result


def preset_supported(adapter, model, space_id, endpoint):
    if adapter == "demucs_multistem":
        from .demucs import MULTISTEM_HOST, MULTISTEM_SPACE

        return (
            model == "htdemucs"
            and space_id == MULTISTEM_SPACE
            and (endpoint is None or endpoint.rstrip("/") == MULTISTEM_HOST)
        )
    models = {
        "nvidia_stream": "nemotron-diarization",
        "omnivoice": "OmniVoice",
        "demucs": "htdemucs_ft",
    }
    if adapter in models and model != models[adapter]:
        return False
    if adapter == "nvidia_stream":
        return (
            space_id == "nvidia/nemotron-diarization"
            and (endpoint or "").rstrip("/") == "https://nvidia-nemotron-diarization.hf.space"
        )
    return True

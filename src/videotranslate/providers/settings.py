from sqlalchemy import select

from ..models.providers import ProviderConnectionRevision
from .catalog import ADAPTERS
from .catalog import SLOTS as SLOTS


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

    spec = ADAPTERS.get(adapter)
    if (
        spec is None
        or not isinstance(controls, dict)
        or set(controls) - set(spec.capabilities.controls)
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
    from dataclasses import asdict, replace

    from ..languages.catalog import resolve

    spec = ADAPTERS[adapter]
    supported = list(spec.capabilities.supported_languages)
    if adapter == "omnivoice" and schema is not None:
        try:
            enum = schema["named_endpoints"][spec.gradio_endpoint]["parameters"][1]["type"]["enum"]
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
    capability = replace(spec.capabilities, stage=slot, supported_languages=tuple(supported))
    result = asdict(capability)
    if adapter == "hf_asr" or (slot == "verification" and adapter == "hf_router"):
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
        from .catalog import MULTISTEM_REVISION
        from .demucs import output_mapping

        result.update(
            {
                "outputs": list(output_mapping(adapter)),
                "instrumental_sources": ["drums", "bass", "other"],
                "published_outputs": ["vocals", "instrumental"],
                "api_name": spec.gradio_endpoint.lstrip("/"),
                "model": spec.fixed_model,
                "space_revision": MULTISTEM_REVISION,
                "credential_mode": "public_demo",
            }
        )
    return result


def preset_supported(adapter, model, space_id, endpoint):
    spec = ADAPTERS.get(adapter)
    if spec is None:
        return True
    if spec.fixed_model is not None and model != spec.fixed_model:
        return False
    if spec.fixed_space is not None:
        return space_id == spec.fixed_space and (
            (endpoint is None and spec.endpoint_optional)
            or (endpoint or "").rstrip("/") == spec.fixed_endpoint
        )
    return True

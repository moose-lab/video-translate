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
        "hf_router": set(),
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

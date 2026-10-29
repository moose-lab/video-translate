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

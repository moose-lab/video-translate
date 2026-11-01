"""Private encrypted URL command; public execution contains only owned IDs."""

from sqlalchemy import CheckConstraint, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base
from .dubbing import Owned, owned_fk, owner_constraints


class SourceImport(Owned, Base):
    __tablename__ = "source_imports"
    __table_args__ = owner_constraints("source_import") + (
        owned_fk("run_id", "stage_runs", "fk_source_import_run"),
        owned_fk("source_asset_id", "assets", "fk_source_import_asset"),
        owned_fk("probe_run_id", "stage_runs", "fk_source_import_probe"),
        UniqueConstraint("project_id", "signature", name="uq_source_import_signature"),
        CheckConstraint("adapter IN ('direct','youtube')", name="ck_source_import_adapter"),
        CheckConstraint("expected_revision > 0", name="ck_source_import_revision"),
    )
    actor_id: Mapped[str] = mapped_column(String(36))
    encrypted_url: Mapped[str] = mapped_column(Text)
    adapter: Mapped[str] = mapped_column(String(20))
    signature: Mapped[str] = mapped_column(String(64))
    expected_revision: Mapped[int] = mapped_column(Integer)
    run_id: Mapped[str | None] = mapped_column(String(36))
    source_asset_id: Mapped[str | None] = mapped_column(String(36))
    probe_run_id: Mapped[str | None] = mapped_column(String(36))

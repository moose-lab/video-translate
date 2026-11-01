"""One owned immutable delivery capture; media phase manifests live in its operation."""

from sqlalchemy import JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base
from .dubbing import Owned, owned_fk, owner_constraints


class DeliveryCommand(Owned, Base):
    __tablename__ = "delivery_commands"
    __table_args__ = owner_constraints("delivery_command") + (
        owned_fk("fit_plan_id", "fit_plan_commands", "fk_delivery_fit"),
        owned_fk("fit_result_id", "fit_plan_results", "fk_delivery_result"),
        owned_fk("source_asset_id", "assets", "fk_delivery_source"),
        owned_fk("run_id", "stage_runs", "fk_delivery_run"),
        UniqueConstraint("project_id", "signature", name="uq_delivery_signature"),
        UniqueConstraint("run_id", name="uq_delivery_run"),
    )
    fit_plan_id: Mapped[str] = mapped_column(String(36))
    fit_result_id: Mapped[str] = mapped_column(String(36))
    source_asset_id: Mapped[str] = mapped_column(String(36))
    run_id: Mapped[str | None] = mapped_column(String(36))
    actor_id: Mapped[str] = mapped_column(String(36))
    signature: Mapped[str] = mapped_column(String(64))
    purpose: Mapped[str] = mapped_column(String(24))
    snapshot: Mapped[dict] = mapped_column(JSON)

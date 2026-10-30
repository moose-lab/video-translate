"""Owned versioned fit settings and immutable CPU plan lineage."""

from sqlalchemy import (
    JSON,
    CheckConstraint,
    ForeignKeyConstraint,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base
from .dubbing import Owned, owned_fk, owner_constraints


def settings_family(column, name, *, alter=False):
    return ForeignKeyConstraint(
        [column, "settings_id", "project_id", "workspace_id"],
        ["fit_settings_versions." + k for k in ("id", "settings_id", "project_id", "workspace_id")],
        name=name,
        use_alter=alter,
    )


class FitSettingsState(Owned, Base):
    __tablename__ = "fit_settings_states"
    __table_args__ = owner_constraints("fit_settings_state") + (
        UniqueConstraint("project_id", name="uq_fit_settings_project"),
        ForeignKeyConstraint(
            ["current_version_id", "id", "project_id", "workspace_id"],
            [
                "fit_settings_versions." + k
                for k in ("id", "settings_id", "project_id", "workspace_id")
            ],
            name="fk_fit_settings_current",
            use_alter=True,
        ),
        CheckConstraint("revision >= 0", name="ck_fit_settings_revision"),
    )
    revision: Mapped[int] = mapped_column(Integer, default=0)
    current_version_id: Mapped[str | None] = mapped_column(String(36))


class FitSettingsVersion(Owned, Base):
    __tablename__ = "fit_settings_versions"
    __table_args__ = owner_constraints("fit_settings_version") + (
        owned_fk("settings_id", "fit_settings_states", "fk_fit_settings_version_root"),
        UniqueConstraint(
            "id", "settings_id", "project_id", "workspace_id", name="uq_fit_settings_version_family"
        ),
        settings_family("parent_version_id", "fk_fit_settings_version_parent"),
        UniqueConstraint("settings_id", "revision", name="uq_fit_settings_version_revision"),
        CheckConstraint(
            "revision > 0 AND policy = 'shared_fit_v1'", name="ck_fit_settings_version"
        ),
    )
    settings_id: Mapped[str] = mapped_column(String(36))
    parent_version_id: Mapped[str | None] = mapped_column(String(36))
    revision: Mapped[int] = mapped_column(Integer)
    settings: Mapped[dict] = mapped_column(JSON)
    policy: Mapped[str] = mapped_column(String(40))
    actor_id: Mapped[str] = mapped_column(String(36))

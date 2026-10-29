"""Workspace provider state and immutable nonsecret connection history."""

from sqlalchemy import JSON, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base
from .core import UTCDateTime, new_id, utcnow


class WorkspaceCredential(Base):
    __tablename__ = "workspace_credentials"
    __table_args__ = (UniqueConstraint("workspace_id", "kind"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    kind: Mapped[str] = mapped_column(String(30))
    revision: Mapped[int] = mapped_column(Integer, default=1)
    ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[object] = mapped_column(UTCDateTime(), default=utcnow)


class ProviderConnection(Base):
    __tablename__ = "provider_connections"
    __table_args__ = (UniqueConstraint("workspace_id", "slot"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    slot: Mapped[str] = mapped_column(String(30))
    revision: Mapped[int] = mapped_column(Integer, default=1)
    settings: Mapped[dict] = mapped_column(JSON)
    check_state: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    updated_at: Mapped[object] = mapped_column(UTCDateTime(), default=utcnow)


class ProviderConnectionRevision(Base):
    __tablename__ = "provider_connection_revisions"
    __table_args__ = (UniqueConstraint("workspace_id", "slot", "revision"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    slot: Mapped[str] = mapped_column(String(30))
    revision: Mapped[int] = mapped_column(Integer)
    settings: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[object] = mapped_column(UTCDateTime(), default=utcnow)

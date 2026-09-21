from datetime import datetime

from sqlalchemy import String, DateTime, Text
from sqlalchemy.orm import Mapped, mapped_column

from database import Base
from lib.time import wib_now
from lib.utils import new_id


class SyncOutbox(Base):
    """Local-only outbox tracking rows that still need to be pushed to the server."""

    __tablename__ = "sync_outbox"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    table_name: Mapped[str] = mapped_column(String(50), index=True)
    row_id: Mapped[str] = mapped_column(String(36), index=True)
    op: Mapped[str] = mapped_column(String(10), default="upsert")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=wib_now)
    synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class SyncMarker(Base):
    """Local-only bookkeeping of the last successful sync timestamp."""

    __tablename__ = "sync_markers"

    table_name: Mapped[str] = mapped_column(String(50), primary_key=True)
    last_synced_at: Mapped[datetime] = mapped_column(DateTime, default=wib_now)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
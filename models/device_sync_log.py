from datetime import datetime

from sqlalchemy import String, DateTime, Text, JSON, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base
from lib.soft_delete import deleted_at_column
from lib.time import wib_now
from lib.utils import new_id


class DeviceSyncLog(Base):
    """One row per bidirectional sync action for a device.

    Per-table pull/push counters and errors live in ``tables``, e.g.
    {"voucher": {"pulled": 40, "pushed": 10, "failed": 2, "errors": [...]}}.
    ``error`` is a one-line summary for list display. Append-only.

    ``type`` is the kind of the action, orthogonal to ``trigger``:
    - "push"  -- server -> kiosk data delivery (kiosk GET requests logged by
      the liveness middleware; status_trigger polling never logs);
    - "pull"  -- kiosk -> server data delivery (POST /sync/bulk);
    - NULL    -- legacy rows and failed non-GET, non-bulk requests.
    """

    __tablename__ = "device_sync_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    device_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("devices.id", ondelete="CASCADE"), index=True
    )
    trigger: Mapped[str | None] = mapped_column(String(20), nullable=True)
    type: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(20), default="started", index=True)
    tables: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=wib_now, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    meta: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    deleted_at: Mapped[datetime | None] = deleted_at_column()

    device: Mapped["Device"] = relationship("Device")

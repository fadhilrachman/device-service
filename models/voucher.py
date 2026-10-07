from datetime import datetime

from sqlalchemy import String, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base
from lib.time import wib_now
from lib.utils import new_id


class Voucher(Base):
    __tablename__ = "vouchers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    batch_id: Mapped[str] = mapped_column(String(36), ForeignKey("voucher_batches.id", ondelete="CASCADE"), index=True)
    code: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(40), default="available", index=True)
    session_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("sessions.id", ondelete="SET NULL"), nullable=True, unique=True)
    device_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("devices.id", ondelete="SET NULL"), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    issued_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=wib_now)
    # Column already exists in the shared schema (backend2 owns it and writes it
    # on every voucher change). It was missing here, which made "changed since
    # devices.last_synced_at" impossible to express in the ORM.
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=wib_now, onupdate=wib_now)

    batch: Mapped["VoucherBatch"] = relationship("VoucherBatch", back_populates="vouchers")
    session: Mapped["SessionModel | None"] = relationship("SessionModel")
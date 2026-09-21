from datetime import datetime
from decimal import Decimal

from sqlalchemy import String, Numeric, DateTime, JSON, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from database import Base
from lib.time import wib_now
from lib.utils import new_id


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    booth_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("booths.id", ondelete="SET NULL"), nullable=True, index=True)
    campaign_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("campaigns.id", ondelete="SET NULL"), nullable=True)
    device_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("devices.id", ondelete="SET NULL"), nullable=True, index=True)
    voucher_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("vouchers.id", ondelete="SET NULL"), nullable=True)
    session_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("sessions.id", ondelete="SET NULL"), nullable=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(8), default="IDR")
    method: Mapped[str | None] = mapped_column(String(40), nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="pending", index=True)
    provider: Mapped[str] = mapped_column(String(40), default="stub")
    provider_ref: Mapped[str | None] = mapped_column(String(100), nullable=True, unique=True, index=True)
    gateway_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=wib_now, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=wib_now, onupdate=wib_now)
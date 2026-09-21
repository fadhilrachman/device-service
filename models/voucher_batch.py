from sqlalchemy import String, Boolean, DateTime, JSON, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from database import Base
from lib.utils import new_id


class VoucherBatch(Base):
    __tablename__ = "voucher_batches"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    campaign_id: Mapped[str | None] = mapped_column(String(36), ForeignKey('campaigns.id', ondelete='CASCADE'), nullable=True)
    name: Mapped[str] = mapped_column(String(200))
    entitlement_rules: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    offline_eligible: Mapped[bool] = mapped_column(Boolean, default=False)

    vouchers: Mapped[list["Voucher"]] = relationship("Voucher", back_populates="batch", cascade="all, delete-orphan")

    @property
    def voucher_count(self) -> int:
        return len(self.vouchers)
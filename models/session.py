from enum import Enum
from sqlalchemy import String, Integer, Boolean, DateTime, JSON, ForeignKey
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from database import Base
from lib.utils import new_id
from lib.time import wib_now
from datetime import datetime


def _enum_values(members) -> list[str]:
    return [m.value for m in members]


class ActivationMode(str, Enum):
    QR = "qr"
    VOUCHER = "voucher"


class SessionState(str, Enum):
    STARTED = "started"
    PAYMENT_CHOICE = "payment_choice"
    SIMULATION = "simulation"
    TAKE_PHOTO = "take_photo"
    RE_TAKE = "re_take"
    PRINT = "print"
    COMPLETE = "complete"
    CANCELLED = "cancelled"


class SessionModel(Base):
    __tablename__ = "sessions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    campaign_id: Mapped[str | None] = mapped_column(String(36), ForeignKey('campaigns.id', ondelete='SET NULL'), nullable=True, index=True)
    booth_id: Mapped[str | None] = mapped_column(String(36), ForeignKey('booths.id', ondelete='SET NULL'), nullable=True, index=True)
    device_id: Mapped[str | None] = mapped_column(String(36), ForeignKey('devices.id', ondelete='SET NULL'), nullable=True, index=True)
    frame_template_id: Mapped[str | None] = mapped_column(String(36), ForeignKey('frame_templates.id', ondelete='SET NULL'), nullable=True, index=True)
    activation_mode: Mapped[ActivationMode | None] = mapped_column(
        SAEnum(ActivationMode, name="activation_mode", values_callable=_enum_values),
        nullable=True,
    )
    state: Mapped[SessionState] = mapped_column(
        SAEnum(SessionState, name="session_state", values_callable=_enum_values),
        default=SessionState.STARTED,
        index=True,
    )
    config_snapshot_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    offline: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=wib_now, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=wib_now, onupdate=wib_now)

    device_logs: Mapped[list["SessionDeviceLog"]] = relationship(
        "SessionDeviceLog",
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="SessionDeviceLog.created_at",
    )
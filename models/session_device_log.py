from datetime import datetime

from sqlalchemy import String, DateTime, Text, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base
from lib.time import wib_now
from lib.utils import new_id


class SessionDeviceLog(Base):
    __tablename__ = "session_device_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    session_id: Mapped[str] = mapped_column(String(36), ForeignKey("sessions.id", ondelete="CASCADE"), index=True)
    device_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("devices.id", ondelete="SET NULL"), nullable=True, index=True)
    camera_profile_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("camera_profiles.id", ondelete="SET NULL"), nullable=True)
    printer_profile_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("printer_profiles.id", ondelete="SET NULL"), nullable=True)
    frame_template_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("frame_templates.id", ondelete="SET NULL"), nullable=True)
    device_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    camera_profile_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    printer_profile_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    frame_template_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    reason: Mapped[str] = mapped_column(String(40), default="created")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=wib_now)

    session: Mapped["SessionModel"] = relationship("SessionModel", back_populates="device_logs")
    device: Mapped["Device | None"] = relationship("Device")
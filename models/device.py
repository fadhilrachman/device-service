from sqlalchemy import String, Integer, Boolean, DateTime, JSON, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from database import Base
from lib.time import wib_now
from lib.utils import new_id
from datetime import datetime


class Device(Base):
    __tablename__ = "devices"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    device_code: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    device_code_sso: Mapped[str | None] = mapped_column(String(255), nullable=True, unique=True, index=True)
    user_code_sso: Mapped[str | None] = mapped_column(String(32), nullable=True)
    tenant_id: Mapped[str | None] = mapped_column(String(36), nullable=True, unique=True, index=True)
    name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    serial_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(String(40), default='active', index=True)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    is_sync_status: Mapped[bool] = mapped_column(Boolean, default=False)
    capabilities: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    camera_profile_id: Mapped[str | None] = mapped_column(String(36), ForeignKey('camera_profiles.id', ondelete='SET NULL'), nullable=True, unique=True)
    printer_profile_id: Mapped[str | None] = mapped_column(String(36), ForeignKey('printer_profiles.id', ondelete='SET NULL'), nullable=True, unique=True)
    app_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_heartbeat: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=wib_now)
    # No onupdate: heartbeat touches must NOT bump this. Matches backend2.
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=wib_now)
    # Deploy signal: rows are born 'disconnect' (server default); the kiosk
    # flips it to 'connect' on its first successful POST /auth/device/token.
    connectivity: Mapped[str | None] = mapped_column(Text, nullable=True, default="disconnect")
    storage_state: Mapped[str | None] = mapped_column(Text, nullable=True)
    camera_health: Mapped[str | None] = mapped_column(Text, nullable=True)
    printer_health: Mapped[str | None] = mapped_column(Text, nullable=True)

    camera_profile: Mapped["CameraProfile | None"] = relationship("CameraProfile")
    printer_profile: Mapped["PrinterProfile | None"] = relationship("PrinterProfile")
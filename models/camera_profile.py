from sqlalchemy import String, Integer, Boolean, DateTime
from sqlalchemy.orm import Mapped, mapped_column
from database import Base
from lib.soft_delete import deleted_at_column
from lib.time import wib_now
from lib.utils import new_id
from datetime import datetime


class CameraProfile(Base):
    __tablename__ = "camera_profiles"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(200))
    image: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[bool] = mapped_column(Boolean, default=True)
    resolution: Mapped[str | None] = mapped_column(String(100), nullable=True)
    aspect_ratio: Mapped[str | None] = mapped_column(String(50), nullable=True)
    orientation: Mapped[str | None] = mapped_column(String(50), nullable=True)
    mirror_preview: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    exposure: Mapped[str | None] = mapped_column(String(50), nullable=True)
    iso: Mapped[int | None] = mapped_column(Integer, nullable=True)
    shutter: Mapped[str | None] = mapped_column(String(50), nullable=True)
    aperture: Mapped[str | None] = mapped_column(String(50), nullable=True)
    white_balance: Mapped[str | None] = mapped_column(String(50), nullable=True)
    focus_mode: Mapped[str | None] = mapped_column(String(50), nullable=True)
    flash: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    trigger: Mapped[str | None] = mapped_column(String(50), nullable=True)
    warm_up: Mapped[int | None] = mapped_column(Integer, nullable=True)
    capture_timeout: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=wib_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=wib_now, onupdate=wib_now)
    deleted_at: Mapped[datetime | None] = deleted_at_column()
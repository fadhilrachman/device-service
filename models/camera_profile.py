from sqlalchemy import String, Integer, Boolean, DateTime, JSON
from sqlalchemy.dialects.postgresql import JSONB
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
    battery: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source: Mapped[str | None] = mapped_column(String(100), nullable=True)
    adapter: Mapped[dict | None] = mapped_column(JSONB().with_variant(JSON(), "sqlite"), nullable=True)
    capture_settings: Mapped[dict | None] = mapped_column(JSONB().with_variant(JSON(), "sqlite"), nullable=True)
    video_settings: Mapped[dict | None] = mapped_column(JSONB().with_variant(JSON(), "sqlite"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=wib_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=wib_now, onupdate=wib_now)
    deleted_at: Mapped[datetime | None] = deleted_at_column()
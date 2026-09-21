from sqlalchemy import String, Integer, Boolean, JSON
from sqlalchemy.orm import Mapped, mapped_column
from database import Base
from lib.utils import new_id


class PrinterProfile(Base):
    __tablename__ = "printer_profiles"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(200))
    image: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[bool] = mapped_column(Boolean, default=True)
    connection: Mapped[str | None] = mapped_column(String(50), nullable=True)
    driver_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    transport: Mapped[str | None] = mapped_column(String(50), nullable=True)
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    device_identifier: Mapped[str | None] = mapped_column(String(100), nullable=True)
    dpi: Mapped[int | None] = mapped_column(Integer, nullable=True)
    width_dots: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_height_dots: Mapped[int | None] = mapped_column(Integer, nullable=True)
    media_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    label_width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    label_height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    darkness: Mapped[int | None] = mapped_column(Integer, nullable=True)
    speed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cut: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    feed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    margins: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    dither: Mapped[str | None] = mapped_column(String(50), nullable=True)
    qr_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    template: Mapped[str | None] = mapped_column(String(200), nullable=True)
    retry_policy: Mapped[str | None] = mapped_column(String(50), nullable=True)
    calibration_offsets: Mapped[dict | None] = mapped_column(JSON, nullable=True)
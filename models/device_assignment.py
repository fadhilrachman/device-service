from sqlalchemy import String, Integer, Boolean, DateTime, JSON, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from database import Base
from lib.utils import new_id
from datetime import datetime


class DeviceAssignment(Base):
    __tablename__ = "device_assignments"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    booth_id: Mapped[str] = mapped_column(String(36), ForeignKey('booths.id', ondelete='CASCADE'))
    device_id: Mapped[str] = mapped_column(String(36), ForeignKey('devices.id', ondelete='CASCADE'))
    assigned_from: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    assigned_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(40), default='active')

    booth: Mapped["Booth"] = relationship("Booth")
    device: Mapped["Device"] = relationship("Device")
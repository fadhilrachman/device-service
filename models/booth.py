from sqlalchemy import String, Integer, Boolean, DateTime, JSON, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from database import Base
from lib.utils import new_id
from datetime import datetime


class Booth(Base):
    __tablename__ = "booths"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    campaign_id: Mapped[str | None] = mapped_column(String(36), ForeignKey('campaigns.id', ondelete='SET NULL'), nullable=True)
    name: Mapped[str] = mapped_column(String(200))
    location: Mapped[str | None] = mapped_column(String(200), nullable=True)
    status: Mapped[str] = mapped_column(String(40), default='active', index=True)
    config_override: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    campaign: Mapped["Campaign | None"] = relationship("Campaign")
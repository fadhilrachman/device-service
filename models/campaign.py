from decimal import Decimal
from datetime import datetime

from sqlalchemy import String, Integer, Boolean, DateTime, JSON, ForeignKey, Numeric
from sqlalchemy.orm import Mapped, mapped_column, relationship
from database import Base
from lib.utils import new_id
from models.campaign_frame_template import campaign_frame_templates


class Campaign(Base):
    __tablename__ = "campaigns"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(40), default='draft', index=True)
    price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    session_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    active_from: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    active_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    activation_rules: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    frame_set: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    print_policy: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    delivery_policy: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    frame_templates: Mapped[list["FrameTemplate"]] = relationship(
        "FrameTemplate",
        secondary=campaign_frame_templates,
        back_populates="campaigns",
    )
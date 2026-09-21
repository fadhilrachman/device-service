from enum import Enum

from sqlalchemy import Enum as SAEnum
from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base
from lib.utils import new_id
from models.campaign_frame_template import campaign_frame_templates


class PublishState(str, Enum):
    DRAFT = "draft"
    PUBLIC = "public"
    ARCHIVE = "archive"


class FrameTemplate(Base):
    __tablename__ = "frame_templates"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(200))
    version: Mapped[str] = mapped_column(String(80))
    assets: Mapped[str] = mapped_column(Text, default="")
    aspect: Mapped[str] = mapped_column(String(40))
    dimensions: Mapped[str] = mapped_column(Text, default="")
    safe_area: Mapped[str] = mapped_column(Text, default="")
    transforms: Mapped[str] = mapped_column(Text, default="")
    preview_variant: Mapped[str] = mapped_column(Text, default="")
    print_variant: Mapped[str] = mapped_column(Text, default="")
    digital_variant: Mapped[str] = mapped_column(Text, default="")
    checksum: Mapped[str] = mapped_column(String(128))
    compatibility: Mapped[str] = mapped_column(Text, default="")
    publish_state: Mapped[PublishState] = mapped_column(
        SAEnum(PublishState, name="frame_template_publish_state"),
        default=PublishState.DRAFT,
        index=True,
    )

    campaigns: Mapped[list["Campaign"]] = relationship(
        "Campaign",
        secondary=campaign_frame_templates,
        back_populates="frame_templates",
    )
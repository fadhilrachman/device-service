from sqlalchemy import String, Column, ForeignKey, Table
from database import Base

campaign_frame_templates = Table(
    "campaign_frame_templates",
    Base.metadata,
    Column("campaign_id", String(36), ForeignKey("campaigns.id", ondelete="CASCADE"), primary_key=True),
    Column("frame_template_id", String(36), ForeignKey("frame_templates.id", ondelete="CASCADE"), primary_key=True),
)
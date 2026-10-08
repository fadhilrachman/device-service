from typing import Optional

from pydantic import BaseModel


class CampaignSessionLimitResponse(BaseModel):
    """Used session quota of one campaign.

    ``used`` counts sessions in state ``complete`` only. ``remaining`` is
    None when the campaign has no limit (``session_limit`` null).
    """

    campaign_id: str
    session_limit: Optional[int] = None
    used: int = 0
    remaining: Optional[int] = None

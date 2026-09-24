from typing import Optional
from pydantic import BaseModel, ConfigDict


class CampaignResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    status: str
    price: Optional[float] = None
    session_limit: Optional[int] = None
    active_from: object = None
    active_until: object = None
    activation_rules: object = None
    frame_set: object = None
    print_policy: object = None
    delivery_policy: object = None


class BoothResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    campaign_id: Optional[str] = None
    name: str
    location: Optional[str] = None
    status: str
    config_override: object = None

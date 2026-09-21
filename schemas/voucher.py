from typing import Optional
from pydantic import BaseModel, ConfigDict


class VoucherResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    batch_id: str
    code: str
    status: str
    session_id: Optional[str] = None
    device_id: Optional[str] = None
    expires_at: object = None
    issued_at: object = None
    used_at: object = None
    created_at: object = None
    offline_eligible: bool = False


class VoucherRedeemRequest(BaseModel):
    session_id: str
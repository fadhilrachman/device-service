from typing import Optional
from pydantic import BaseModel, ConfigDict


class PaymentCreate(BaseModel):
    session_id: Optional[str] = None
    booth_id: Optional[str] = None
    campaign_id: Optional[str] = None
    device_id: Optional[str] = None
    amount: Optional[float] = None
    method: Optional[str] = None


class PaymentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    booth_id: Optional[str] = None
    campaign_id: Optional[str] = None
    device_id: Optional[str] = None
    voucher_id: Optional[str] = None
    session_id: Optional[str] = None
    amount: float
    currency: str
    method: Optional[str] = None
    status: str
    provider: str
    provider_ref: Optional[str] = None
    paid_at: object = None
    created_at: object = None
    updated_at: object = None


class PaymentCreateResponse(BaseModel):
    payment: PaymentResponse
    charge_url: Optional[str] = None
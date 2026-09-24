from typing import Optional
from pydantic import BaseModel, ConfigDict, Field


class PaymentCreate(BaseModel):
    session_id: Optional[str] = None
    booth_id: Optional[str] = Field(
        default=None, description="Defaults to the device's active assignment booth."
    )
    campaign_id: Optional[str] = Field(
        default=None, description="Defaults to the booth's campaign."
    )
    device_id: Optional[str] = Field(
        default=None, description="Defaults to the calling device."
    )
    amount: Optional[float] = Field(
        default=None, description="Defaults to the campaign price."
    )
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
    gateway_payload: Optional[dict] = None
    paid_at: object = None
    created_at: object = None
    updated_at: object = None


class PaymentCreateResponse(BaseModel):
    payment: PaymentResponse
    charge_url: Optional[str] = None
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field


class PaymentCreate(BaseModel):
    # Strict contract: device/booth/campaign come from the device's active
    # assignment server-side. Stale kiosk clients still sending IDs fail
    # loudly (422) instead of being silently ignored.
    model_config = ConfigDict(extra="forbid")
    session_id: Optional[str] = None
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
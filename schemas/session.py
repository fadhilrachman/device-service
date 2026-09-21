from typing import Optional, Generic, TypeVar
from pydantic import BaseModel, ConfigDict

from models.session import ActivationMode, SessionState

T = TypeVar("T")


class BaseListResponse(BaseModel, Generic[T]):
    message: str
    data: list[T]


class SessionCreate(BaseModel):
    frame_template_id: Optional[str] = None
    config_snapshot_id: Optional[str] = None
    offline: bool = False


class SessionUpdate(BaseModel):
    campaign_id: Optional[str] = None
    booth_id: Optional[str] = None
    device_id: Optional[str] = None
    frame_template_id: Optional[str] = None
    activation_mode: Optional[ActivationMode] = None
    state: Optional[SessionState] = None
    config_snapshot_id: Optional[str] = None
    offline: Optional[bool] = None


class SessionPaymentUpdate(BaseModel):
    activation_mode: ActivationMode


class SessionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    campaign_id: Optional[str] = None
    booth_id: Optional[str] = None
    device_id: Optional[str] = None
    frame_template_id: Optional[str] = None
    activation_mode: Optional[ActivationMode] = None
    state: SessionState
    config_snapshot_id: Optional[str] = None
    offline: bool
    created_at: object = None
    updated_at: object = None
    device_code: Optional[str] = None
    frame_template_name: Optional[str] = None
    camera_profile_id: Optional[str] = None
    camera_profile_name: Optional[str] = None
    printer_profile_id: Optional[str] = None
    printer_profile_name: Optional[str] = None
    device_logged_at: object = None


class SessionListResponse(BaseListResponse[SessionResponse]):
    pass
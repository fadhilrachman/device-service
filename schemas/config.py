from typing import Optional
from pydantic import BaseModel, ConfigDict

from schemas.catalog import BoothResponse, CampaignResponse
from schemas.device import DeviceResponse

__all__ = [
    "AssignmentResponse",
    "BoothResponse",
    "CameraProfileResponse",
    "CampaignResponse",
    "DeviceConfigResponse",
    "DeviceResponse",
    "FrameTemplateResponse",
    "PrinterProfileResponse",
]


class CameraProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    image: Optional[str] = None
    status: bool
    resolution: Optional[str] = None
    aspect_ratio: Optional[str] = None
    orientation: Optional[str] = None
    mirror_preview: Optional[bool] = None
    exposure: Optional[str] = None
    iso: Optional[int] = None
    shutter: Optional[str] = None
    aperture: Optional[str] = None
    white_balance: Optional[str] = None
    focus_mode: Optional[str] = None
    flash: Optional[bool] = None
    trigger: Optional[str] = None
    warm_up: Optional[int] = None
    capture_timeout: Optional[int] = None


class PrinterProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    image: Optional[str] = None
    status: bool
    connection: Optional[str] = None
    driver_type: Optional[str] = None
    transport: Optional[str] = None
    model: Optional[str] = None
    device_identifier: Optional[str] = None
    dpi: Optional[int] = None
    width_dots: Optional[int] = None
    max_height_dots: Optional[int] = None
    media_type: Optional[str] = None
    label_width: Optional[int] = None
    label_height: Optional[int] = None
    darkness: Optional[int] = None
    speed: Optional[int] = None
    cut: Optional[bool] = None
    feed: Optional[int] = None
    margins: object = None
    dither: Optional[str] = None
    qr_size: Optional[int] = None
    template: Optional[str] = None
    retry_policy: Optional[str] = None
    calibration_offsets: object = None


class FrameTemplateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    version: str
    assets: str
    aspect: str
    dimensions: str
    safe_area: str
    transforms: str
    preview_variant: str
    print_variant: str
    digital_variant: str
    checksum: str
    compatibility: str
    publish_state: str


class AssignmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    booth_id: str
    device_id: str
    assigned_from: object = None
    assigned_until: object = None
    status: str


class DeviceConfigResponse(BaseModel):
    device: Optional[DeviceResponse] = None
    assignment: Optional[AssignmentResponse] = None
    booth: Optional[BoothResponse] = None
    campaign: Optional[CampaignResponse] = None
    camera_profile: Optional[CameraProfileResponse] = None
    printer_profile: Optional[PrinterProfileResponse] = None
    frames: list[FrameTemplateResponse] = []
    offline_vouchers: int = 0
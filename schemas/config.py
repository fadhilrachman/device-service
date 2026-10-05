from typing import Any, Optional
from pydantic import BaseModel, ConfigDict, Field

from schemas.catalog import BoothResponse, CampaignResponse  # noqa: F401 (re-export)
from schemas.device import DeviceResponse
from models.frame_template import PublishState

__all__ = [
    "BoothResponse",
    "CameraProfileResponse",
    "CampaignResponse",
    "CampaignConfigResponse",
    "DeviceConfigResponse",
    "DeviceResponse",
    "FrameTemplateResponse",
    "PrinterProfileResponse",
]


class CampaignConfigResponse(CampaignResponse):
    frame_set: list[str] = Field(default_factory=list)


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
    transforms: dict[str, Any]
    preview_variant: str
    print_variant: str
    digital_variant: str
    checksum: str
    compatibility: str
    publish_state: PublishState


class DeviceConfigResponse(BaseModel):
    device: Optional[DeviceResponse] = None
    camera_profile: Optional[CameraProfileResponse] = None
    printer_profile: Optional[PrinterProfileResponse] = None
    frames: list[FrameTemplateResponse] = []
    offline_vouchers: int = 0

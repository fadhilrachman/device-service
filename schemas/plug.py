from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field

_config = {"extra": "ignore"}

NAME_MAX = 200
SOURCE_MAX = 100


class PlugAdapterPreferredDevice(BaseModel):
    model_config = ConfigDict(**_config)
    identifier: Optional[str] = None
    label: Optional[str] = None
    usb_id: Optional[str] = None


class PlugCameraAdapter(BaseModel):
    model_config = ConfigDict(**_config)
    type: Optional[str] = None
    vendor: Optional[str] = None
    model: Optional[str] = None
    allowlist: Optional[List[str]] = None
    preferred_device: Optional[PlugAdapterPreferredDevice] = None


class PlugCameraResolution(BaseModel):
    model_config = ConfigDict(**_config)
    width: Optional[int] = None
    height: Optional[int] = None
    source: Optional[str] = None


class PlugCameraExposure(BaseModel):
    model_config = ConfigDict(**_config)
    mode: Optional[str] = None
    compensation: Optional[str] = None


class PlugCameraFlash(BaseModel):
    model_config = ConfigDict(**_config)
    supported: Optional[bool] = None
    trigger: Optional[str] = None


class PlugCameraCaptureSettings(BaseModel):
    model_config = ConfigDict(**_config)
    resolution: Optional[PlugCameraResolution] = None
    aspect_ratio: Optional[str] = None
    orientation: Optional[str] = None
    mirror_preview: Optional[bool] = None
    exposure: Optional[PlugCameraExposure] = None
    iso: Optional[str] = None
    shutter_speed: Optional[str] = None
    aperture: Optional[str] = None
    white_balance: Optional[str] = None
    focus_mode: Optional[str] = None
    flash: Optional[PlugCameraFlash] = None
    warmup_ms: Optional[int] = None
    capture_timeout_ms: Optional[int] = None


class PlugCameraVideoSettings(BaseModel):
    model_config = ConfigDict(**_config)
    pre_roll_ms: Optional[int] = None
    post_roll_ms: Optional[int] = None
    target_duration_s: Optional[int] = None
    fps: Optional[int] = None
    codec: Optional[str] = None
    bitrate_kbps: Optional[int] = None
    audio_enabled: Optional[bool] = None
    fallback_behavior: Optional[str] = None


class PlugCameraProfile(BaseModel):
    """Kiosk-reported camera. Only ``name`` is required; the rest is stored as-is.

    ``captured_at`` is accepted but intentionally not persisted (there is no
    such column on ``camera_profiles``).
    """

    model_config = ConfigDict(**_config)
    name: str = Field(max_length=NAME_MAX)
    source: Optional[str] = Field(default=None, max_length=SOURCE_MAX)
    captured_at: Optional[datetime] = None
    adapter: Optional[PlugCameraAdapter] = None
    capture_settings: Optional[PlugCameraCaptureSettings] = None
    video_settings: Optional[PlugCameraVideoSettings] = None


class PlugPrinterProfile(BaseModel):
    """Kiosk-reported printer. Name only for now; unknown keys are ignored."""

    model_config = ConfigDict(**_config)
    name: str = Field(max_length=NAME_MAX)


class PlugCameraPrinterRequest(BaseModel):
    model_config = ConfigDict(**_config)
    camera_profile: Optional[PlugCameraProfile] = None
    printer_profile: Optional[PlugPrinterProfile] = None


class PlugCameraProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    source: Optional[str] = None
    adapter: Optional[dict] = None
    capture_settings: Optional[dict] = None
    video_settings: Optional[dict] = None


class PlugPrinterProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str


class PlugCameraPrinterResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    camera_profile: Optional[PlugCameraProfileResponse] = None
    printer_profile: Optional[PlugPrinterProfileResponse] = None

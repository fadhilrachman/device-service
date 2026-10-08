from typing import Optional
from pydantic import BaseModel, ConfigDict, Field

from schemas.catalog import BoothResponse, CampaignResponse


class DeviceHeartbeatRequest(BaseModel):
    # Unknown keys (notably the retired camera_health report) are ignored so
    # older kiosks keep working; only battery is honored for the camera.
    model_config = ConfigDict(extra='ignore')
    storage_state: Optional[str] = None
    battery: Optional[int] = Field(
        default=None, ge=0, le=100, description='Camera battery percent 0-100.'
    )
    printer_health: Optional[str] = None


class DeviceAssignmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    booth_id: str
    device_id: str
    assigned_from: object = None
    assigned_until: object = None
    status: str
    booth_name: Optional[str] = None
    booth_location: Optional[str] = None
    campaign_id: Optional[str] = None
    booth: Optional[BoothResponse] = None
    campaign: Optional[CampaignResponse] = None


class DeviceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    device_code: str
    tenant_id: Optional[str] = None
    name: Optional[str] = None
    serial_number: Optional[str] = None
    status: str
    is_verified: bool = False
    capabilities: object = None
    camera_profile_id: Optional[str] = None
    printer_profile_id: Optional[str] = None
    app_version: Optional[str] = None
    last_synced_at: object = None
    connectivity: Optional[str] = None
    storage_state: Optional[str] = None
    camera_health: Optional[str] = None
    printer_health: Optional[str] = None
    device_assignment: Optional[DeviceAssignmentResponse] = None


class DeviceListResponse(BaseModel):
    message: str
    data: list[DeviceResponse]


class DeviceSyncStatusTriggerResponse(BaseModel):
    is_sync_status_trigger: bool = False
from typing import Optional
from pydantic import BaseModel, ConfigDict

from schemas.catalog import BoothResponse, CampaignResponse


class DeviceHeartbeatRequest(BaseModel):
    storage_state: Optional[str] = None
    camera_health: Optional[str] = None
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
    name: Optional[str] = None
    serial_number: Optional[str] = None
    status: str
    capabilities: object = None
    camera_profile_id: Optional[str] = None
    printer_profile_id: Optional[str] = None
    app_version: Optional[str] = None
    last_seen_at: object = None
    last_heartbeat: object = None
    connectivity: Optional[str] = None
    storage_state: Optional[str] = None
    camera_health: Optional[str] = None
    printer_health: Optional[str] = None
    device_assignment: Optional[DeviceAssignmentResponse] = None


class DeviceListResponse(BaseModel):
    message: str
    data: list[DeviceResponse]
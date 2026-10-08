from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from database import get_db
from lib.device_assignment import get_valid_assignment
from lib.device_identity import require_request_device_id
from lib.time import wib_now
from models.booth import Booth
from models.campaign import Campaign
from models.device import Device
from schemas.catalog import BoothResponse, CampaignResponse
from schemas.device import (
    DeviceAssignmentResponse,
    DeviceHeartbeatRequest,
    DeviceResponse,
    DeviceSyncStatusTriggerResponse,
)

router = APIRouter(prefix="/devices", tags=["devices"])


def _me_response(db: Session, device: Device) -> DeviceResponse:
    response = DeviceResponse.model_validate(device)
    # Window-checked: an assignment outside [assigned_from, assigned_until]
    # (or with an undefined bound) surfaces as null here.
    assignment = get_valid_assignment(db, device.id)
    if assignment:
        assignment_data = DeviceAssignmentResponse.model_validate(assignment)
        booth = db.get(Booth, assignment.booth_id)
        if booth is not None and booth.deleted_at is None:
            assignment_data.booth_name = booth.name
            assignment_data.booth_location = booth.location
            assignment_data.campaign_id = booth.campaign_id
            assignment_data.booth = BoothResponse.model_validate(booth)
            if booth.campaign_id:
                campaign = db.get(Campaign, booth.campaign_id)
                if campaign is not None and campaign.deleted_at is None:
                    assignment_data.campaign = CampaignResponse.model_validate(campaign)
        response.device_assignment = assignment_data
    return response


def _get_device_or_404(db: Session, device_id: str) -> Device:
    device = db.get(Device, device_id)
    print(device)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found.")
    return device


@router.get("/me", response_model=DeviceResponse)
def get_me(request: Request, db: Session = Depends(get_db)):
    return _me_response(db, _get_device_or_404(db, require_request_device_id(db, request)))


@router.get("/sync/status_trigger", response_model=DeviceSyncStatusTriggerResponse)
def get_sync_status_trigger(request: Request, db: Session = Depends(get_db)):
    """Read-only sync flag for the caller (device id from token claim)."""
    device = _get_device_or_404(db, require_request_device_id(db, request))
    return {"is_sync_status_trigger": bool(device.is_sync_status)}


@router.patch("/heartbeat", response_model=DeviceResponse)
def heartbeat(payload: DeviceHeartbeatRequest, request: Request, db: Session = Depends(get_db)):
    device = _get_device_or_404(db, require_request_device_id(db, request))

    now = wib_now()
    device.last_seen_at = now
    device.last_heartbeat = now
    device.connectivity = "online"
    if payload.storage_state is not None:
        device.storage_state = payload.storage_state
    if payload.camera_health is not None:
        device.camera_health = payload.camera_health
    if payload.printer_health is not None:
        device.printer_health = payload.printer_health

    db.commit()
    db.refresh(device)
    return device

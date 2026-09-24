from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from config import resolve_device_id
from database import get_db
from lib.time import wib_now
from models.booth import Booth
from models.campaign import Campaign
from models.device import Device
from models.device_assignment import DeviceAssignment
from schemas.catalog import BoothResponse, CampaignResponse
from schemas.device import (
    DeviceAssignmentResponse,
    DeviceHeartbeatRequest,
    DeviceResponse,
)
from sync import engine

router = APIRouter(prefix="/devices", tags=["devices"])


def _active_assignment(db: Session, device_id: str) -> DeviceAssignment | None:
    return (
        db.query(DeviceAssignment)
        .filter(
            DeviceAssignment.device_id == device_id,
            DeviceAssignment.status == "active",
        )
        .order_by(DeviceAssignment.assigned_from.desc())
        .first()
    )


def _me_response(db: Session, device: Device) -> DeviceResponse:
    response = DeviceResponse.model_validate(device)
    assignment = _active_assignment(db, device.id)
    if assignment:
        assignment_data = DeviceAssignmentResponse.model_validate(assignment)
        booth = db.get(Booth, assignment.booth_id)
        if booth:
            assignment_data.booth_name = booth.name
            assignment_data.booth_location = booth.location
            assignment_data.campaign_id = booth.campaign_id
            assignment_data.booth = BoothResponse.model_validate(booth)
            if booth.campaign_id:
                campaign = db.get(Campaign, booth.campaign_id)
                if campaign:
                    assignment_data.campaign = CampaignResponse.model_validate(campaign)
        response.device_assignment = assignment_data
    return response


@router.get("/me", response_model=DeviceResponse)
def get_me(db: Session = Depends(get_db)):
    device = db.get(Device, resolve_device_id())
    if not device:
        device = engine.ensure_local_device(db)
        db.commit()
        db.refresh(device)
    return _me_response(db, device)


@router.patch("/heartbeat", response_model=DeviceResponse)
def heartbeat(payload: DeviceHeartbeatRequest, db: Session = Depends(get_db)):
    device = db.get(Device, resolve_device_id())
    if not device:
        device = engine.ensure_local_device(db)

    now = wib_now()
    device.last_seen_at = now
    device.last_heartbeat = now
    device.connectivity = "online" if engine.is_online() else "offline"
    if payload.storage_state is not None:
        device.storage_state = payload.storage_state
    if payload.camera_health is not None:
        device.camera_health = payload.camera_health
    if payload.printer_health is not None:
        device.printer_health = payload.printer_health

    db.commit()
    db.refresh(device)
    return device
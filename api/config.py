from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from database import get_db
from lib.device_assignment import get_valid_assignment
from lib.device_identity import require_request_device_id
from models.booth import Booth
from models.campaign import Campaign
from models.camera_profile import CameraProfile
from models.device import Device
from models.frame_template import FrameTemplate
from models.frame_template import PublishState
from models.printer_profile import PrinterProfile
from models.voucher import Voucher
from models.voucher_batch import VoucherBatch
from schemas.config import (
    CameraProfileResponse,
    CampaignConfigResponse,
    CampaignResponse,
    DeviceConfigResponse,
    DeviceResponse,
    FrameTemplateResponse,
    PrinterProfileResponse,
)

router = APIRouter(prefix="/config", tags=["config"])


@router.get("", response_model=DeviceConfigResponse)
def get_config(request: Request, db: Session = Depends(get_db)):
    """Device config bundle only: device, profiles, available frames, voucher count.

    Assignment data (assignment/booth/campaign) is intentionally excluded;
    clients get it from GET /devices/me or GET /config/campaign instead.
    """
    device_id = require_request_device_id(db, request)
    device = db.get(Device, device_id)

    camera = (
        db.get(CameraProfile, device.camera_profile_id)
        if device and device.camera_profile_id
        else None
    )
    printer = (
        db.get(PrinterProfile, device.printer_profile_id)
        if device and device.printer_profile_id
        else None
    )

    campaign = _active_campaign(db, device_id)
    frames = _resolve_frames(db, campaign)

    offline_vouchers = 0
    if campaign:
        # Batch.offline_eligible is legacy data; the admin no longer sets it.
        offline_vouchers = (
            _device_vouchers(db, device_id, campaign)
            .filter(Voucher.status == "available")
            .count()
        )

    return DeviceConfigResponse(
        device=DeviceResponse.model_validate(device) if device else None,
        camera_profile=CameraProfileResponse.model_validate(camera) if camera else None,
        printer_profile=PrinterProfileResponse.model_validate(printer) if printer else None,
        frames=[FrameTemplateResponse.model_validate(f) for f in frames],
        offline_vouchers=offline_vouchers,
    )


@router.get("/campaign", response_model=CampaignConfigResponse)
def get_campaign(request: Request, db: Session = Depends(get_db)):
    campaign = _active_campaign(db, require_request_device_id(db, request))
    if not campaign:
        raise HTTPException(
            status_code=404,
            detail="No active campaign for this device: no assignment or the assignment window has expired.",
        )
    response = CampaignResponse.model_validate(campaign).model_dump()
    response["frame_set"] = [
        frame.id for frame in sorted(campaign.frame_templates, key=lambda frame: (frame.name, frame.id))
    ]
    return CampaignConfigResponse.model_validate(response)


@router.get("/profiles", response_model=dict)
def get_profiles(request: Request, db: Session = Depends(get_db)):
    device = db.get(Device, require_request_device_id(db, request))
    camera = (
        db.get(CameraProfile, device.camera_profile_id)
        if device and device.camera_profile_id
        else None
    )
    printer = (
        db.get(PrinterProfile, device.printer_profile_id)
        if device and device.printer_profile_id
        else None
    )
    return {
        "camera_profile": CameraProfileResponse.model_validate(camera) if camera else None,
        "printer_profile": PrinterProfileResponse.model_validate(printer) if printer else None,
    }


def _active_campaign(db: Session, device_id: str) -> Campaign | None:
    assignment = get_valid_assignment(db, device_id)
    if not assignment:
        return None
    booth = db.get(Booth, assignment.booth_id)
    if not booth or not booth.campaign_id:
        return None
    return db.get(Campaign, booth.campaign_id)


def _device_vouchers(db: Session, device_id: str, campaign: Campaign):
    return (
        db.query(Voucher)
        .join(VoucherBatch, Voucher.batch_id == VoucherBatch.id)
        .filter(
            VoucherBatch.campaign_id == campaign.id,
            Voucher.device_id == device_id,
        )
    )


def _resolve_frames(db: Session, campaign: Campaign | None) -> list[FrameTemplate]:
    if campaign:
        linked = [
            f
            for f in campaign.frame_templates
            if f.publish_state is PublishState.PUBLIC
        ]
        if linked:
            return sorted(linked, key=lambda frame: (frame.name, frame.id))
    return (
        db.query(FrameTemplate)
        .filter(FrameTemplate.publish_state == PublishState.PUBLIC)
        .order_by(FrameTemplate.name, FrameTemplate.id)
        .all()
    )

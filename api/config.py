from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from config import resolve_device_id
from database import get_db
from models.booth import Booth
from models.campaign import Campaign
from models.camera_profile import CameraProfile
from models.device import Device
from models.device_assignment import DeviceAssignment
from models.frame_template import FrameTemplate
from models.frame_template import PublishState
from models.printer_profile import PrinterProfile
from models.voucher import Voucher
from models.voucher_batch import VoucherBatch
from schemas.config import (
    AssignmentResponse,
    BoothResponse,
    CameraProfileResponse,
    CampaignResponse,
    DeviceConfigResponse,
    DeviceResponse,
    FrameTemplateResponse,
    PrinterProfileResponse,
)
from sync import engine

router = APIRouter(prefix="/config", tags=["config"])


@router.get("", response_model=DeviceConfigResponse)
def get_config(db: Session = Depends(get_db)):
    device_id = resolve_device_id()
    device = db.get(Device, device_id)

    assignment = (
        db.query(DeviceAssignment)
        .filter(
            DeviceAssignment.device_id == device_id,
            DeviceAssignment.status == "active",
        )
        .order_by(DeviceAssignment.assigned_from.desc())
        .first()
    )
    booth = db.get(Booth, assignment.booth_id) if assignment else None
    campaign = (
        db.get(Campaign, booth.campaign_id)
        if booth and booth.campaign_id
        else None
    )

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

    frames = _resolve_frames(db, campaign)

    offline_vouchers = (
        db.query(Voucher)
        .join(VoucherBatch)
        .filter(VoucherBatch.offline_eligible.is_(True), Voucher.status == "available")
        .count()
    )

    return DeviceConfigResponse(
        device=DeviceResponse.model_validate(device) if device else None,
        assignment=AssignmentResponse.model_validate(assignment) if assignment else None,
        booth=BoothResponse.model_validate(booth) if booth else None,
        campaign=CampaignResponse.model_validate(campaign) if campaign else None,
        camera_profile=CameraProfileResponse.model_validate(camera) if camera else None,
        printer_profile=PrinterProfileResponse.model_validate(printer) if printer else None,
        frames=[FrameTemplateResponse.model_validate(f) for f in frames],
        offline_vouchers=offline_vouchers,
    )


@router.get("/campaign", response_model=CampaignResponse)
def get_campaign(db: Session = Depends(get_db)):
    campaign = _active_campaign(db)
    if not campaign:
        raise HTTPException(status_code=404, detail="No active campaign for this device.")
    return campaign


@router.get("/profiles", response_model=dict)
def get_profiles(db: Session = Depends(get_db)):
    device = db.get(Device, resolve_device_id())
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


def _active_campaign(db: Session) -> Campaign | None:
    device_id = resolve_device_id()
    assignment = (
        db.query(DeviceAssignment)
        .filter(
            DeviceAssignment.device_id == device_id,
            DeviceAssignment.status == "active",
        )
        .order_by(DeviceAssignment.assigned_from.desc())
        .first()
    )
    if not assignment:
        return None
    booth = db.get(Booth, assignment.booth_id)
    if not booth or not booth.campaign_id:
        return None
    return db.get(Campaign, booth.campaign_id)


def _resolve_frames(db: Session, campaign: Campaign | None) -> list[FrameTemplate]:
    if campaign:
        linked = [
            f
            for f in campaign.frame_templates
            if f.publish_state is PublishState.PUBLIC
        ]
        if linked:
            return linked
    return (
        db.query(FrameTemplate)
        .filter(FrameTemplate.publish_state == PublishState.PUBLIC)
        .order_by(FrameTemplate.name)
        .all()
    )
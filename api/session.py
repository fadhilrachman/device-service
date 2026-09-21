from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, selectinload

from api.config import _resolve_frames
from config import resolve_device_id
from database import get_db
from lib.outbox import enqueue
from models.booth import Booth
from models.camera_profile import CameraProfile
from models.campaign import Campaign
from models.device import Device
from models.device_assignment import DeviceAssignment
from models.frame_template import FrameTemplate, PublishState
from models.printer_profile import PrinterProfile
from models.session import SessionModel, SessionState
from models.session_device_log import SessionDeviceLog
from schemas.session import (
    SessionCreate,
    SessionListResponse,
    SessionPaymentUpdate,
    SessionResponse,
    SessionUpdate,
)
from sync import engine

router = APIRouter(prefix="/sessions", tags=["sessions"])

# lifecycle: action -> (allowed_source_state, next_state)
ACTIONS: dict[str, tuple[str, str]] = {
    "simulation": ("simulation", "take_photo"),
    "retake": ("take_photo", "re_take"),
    "photo": ("re_take", "take_photo"),
    "print": ("take_photo", "print"),
}
FRAME_SETTER_STATES = {"started", "payment_choice"}
CANCELLABLE = {"started", "payment_choice", "simulation", "take_photo", "re_take", "print"}


def _attach_snapshot(db_obj: SessionModel) -> SessionResponse:
    latest = db_obj.device_logs[-1] if db_obj.device_logs else None
    response = SessionResponse.model_validate(db_obj)
    if latest:
        response.device_code = latest.device_code
        response.camera_profile_id = latest.camera_profile_id
        response.camera_profile_name = latest.camera_profile_name
        response.printer_profile_id = latest.printer_profile_id
        response.printer_profile_name = latest.printer_profile_name
        response.frame_template_name = latest.frame_template_name
        response.device_logged_at = latest.created_at
    return response


def _snapshot_payload(db: Session, device: Device | None, frame_id: str | None) -> dict:
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
    frame = db.get(FrameTemplate, frame_id) if frame_id else None
    return {
        "device_id": device.id if device else None,
        "device_code": device.device_code if device else None,
        "camera_profile_id": camera.id if camera else None,
        "camera_profile_name": camera.name if camera else None,
        "printer_profile_id": printer.id if printer else None,
        "printer_profile_name": printer.name if printer else None,
        "frame_template_id": frame.id if frame else None,
        "frame_template_name": frame.name if frame else None,
    }


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


def _session_campaign(
    db: Session, session: SessionModel, device: Device | None = None
) -> Campaign | None:
    if device is None and session.device_id:
        device = db.get(Device, session.device_id)
    if not device:
        return None
    assignment = _active_assignment(db, device.id)
    if not assignment:
        return None
    booth = db.get(Booth, assignment.booth_id)
    if not booth or not booth.campaign_id:
        return None
    return db.get(Campaign, booth.campaign_id)


def _apply_frame(
    db: Session, session: SessionModel, frame_id: str, device: Device | None
) -> None:
    frame = db.get(FrameTemplate, frame_id)
    if not frame or frame.publish_state is not PublishState.PUBLIC:
        raise HTTPException(status_code=400, detail="Frame template is not available.")
    campaign = _session_campaign(db, session, device)
    allowed = {f.id for f in _resolve_frames(db, campaign)}
    if frame_id not in allowed:
        raise HTTPException(
            status_code=400,
            detail="Frame template is not available for this campaign.",
        )
    if session.state not in FRAME_SETTER_STATES and session.frame_template_id != frame_id:
        raise HTTPException(status_code=400, detail="Frame template is locked.")
    session.frame_template_id = frame_id


def _get_or_404(db: Session, id: str) -> SessionModel:
    db_obj = (
        db.query(SessionModel)
        .options(selectinload(SessionModel.device_logs))
        .filter(SessionModel.id == id)
        .first()
    )
    if not db_obj:
        raise HTTPException(status_code=404, detail="Session not found")
    return db_obj


def _step(db: Session, db_obj: SessionModel, action: str) -> SessionResponse:
    allowed_from, next_state = ACTIONS[action]
    if db_obj.state != allowed_from:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot {action} session in state '{db_obj.state}'",
        )
    db_obj.state = next_state
    device = db.get(Device, db_obj.device_id) if db_obj.device_id else None
    try:
        enqueue(db, "sessions", db_obj.id)
        _write_log(db, db_obj, device, action)
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(db_obj)
    return _attach_snapshot(db_obj)


def _write_log(db: Session, db_obj: SessionModel, device: Device | None, reason: str) -> None:
    log = SessionDeviceLog(
        session_id=db_obj.id,
        reason=reason,
        **_snapshot_payload(db, device, db_obj.frame_template_id),
    )
    db.add(log)
    db.flush()
    enqueue(db, "session_device_logs", log.id)


@router.post("", response_model=SessionResponse, status_code=status.HTTP_201_CREATED)
def create_session(payload: SessionCreate, db: Session = Depends(get_db)):
    device_id = resolve_device_id()
    device = db.get(Device, device_id)
    if not device:
        device = engine.ensure_local_device(db)
    if device.status != "active":
        raise HTTPException(status_code=409, detail="Device is not active.")

    assignment = _active_assignment(db, device.id)
    booth_id = assignment.booth_id if assignment else None
    campaign_id = None
    if assignment:
        booth = db.get(Booth, assignment.booth_id)
        if booth:
            campaign_id = booth.campaign_id

    offline = payload.offline or not engine.is_online()
    db_obj = SessionModel(
        campaign_id=campaign_id,
        booth_id=booth_id,
        device_id=device.id,
        frame_template_id=payload.frame_template_id,
        state=SessionState.STARTED,
        config_snapshot_id=payload.config_snapshot_id,
        offline=offline,
    )
    if payload.frame_template_id:
        _apply_frame(db, db_obj, payload.frame_template_id, device)
    db.add(db_obj)
    try:
        db.flush()
        enqueue(db, "sessions", db_obj.id)
        _write_log(db, db_obj, device, "created")
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(db_obj)
    return _attach_snapshot(db_obj)


@router.get("", response_model=SessionListResponse)
def list_sessions(limit: int = 20, db: Session = Depends(get_db)):
    items = (
        db.query(SessionModel)
        .options(selectinload(SessionModel.device_logs))
        .order_by(SessionModel.created_at.desc())
        .limit(limit)
        .all()
    )
    return SessionListResponse(
        message="Success get sessions",
        data=[_attach_snapshot(item) for item in items],
    )


@router.get("/{id}", response_model=SessionResponse)
def get_session(id: str, db: Session = Depends(get_db)):
    return _attach_snapshot(_get_or_404(db, id))


@router.patch("/{id}", response_model=SessionResponse)
def update_session(id: str, payload: SessionUpdate, db: Session = Depends(get_db)):
    db_obj = _get_or_404(db, id)

    old_device_id = db_obj.device_id
    update_data = payload.model_dump(exclude_unset=True)
    if "frame_template_id" in update_data and payload.frame_template_id is not None:
        device = db.get(Device, payload.device_id) if payload.device_id else db.get(Device, db_obj.device_id)
        _apply_frame(db, db_obj, payload.frame_template_id, device)
    for k, v in update_data.items():
        setattr(db_obj, k, v)

    try:
        if payload.device_id and payload.device_id != old_device_id:
            device = db.get(Device, payload.device_id)
            if not device:
                raise HTTPException(status_code=404, detail="Device not found.")
            _write_log(db, db_obj, device, "device_swap")
        enqueue(db, "sessions", db_obj.id)
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(db_obj)
    return _attach_snapshot(db_obj)


@router.patch("/{session_id}/payment", response_model=SessionResponse)
def update_session_payment(
    session_id: str, payload: SessionPaymentUpdate, db: Session = Depends(get_db)
):
    db_obj = _get_or_404(db, session_id)
    if db_obj.state not in {"started", "payment_choice"}:
        raise HTTPException(
            status_code=409,
            detail="Activation mode can only be set before the photo session starts.",
        )
    db_obj.activation_mode = payload.activation_mode
    try:
        enqueue(db, "sessions", db_obj.id)
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(db_obj)
    return _attach_snapshot(db_obj)


@router.patch("/{session_id}/simulation", response_model=SessionResponse)
def simulation_session(session_id: str, db: Session = Depends(get_db)):
    return _step(db, _get_or_404(db, session_id), "simulation")


@router.patch("/{session_id}/retake", response_model=SessionResponse)
def retake_session(session_id: str, db: Session = Depends(get_db)):
    return _step(db, _get_or_404(db, session_id), "retake")


@router.patch("/{session_id}/photo", response_model=SessionResponse)
def photo_session(session_id: str, db: Session = Depends(get_db)):
    return _step(db, _get_or_404(db, session_id), "photo")


@router.patch("/{session_id}/print", response_model=SessionResponse)
def print_session(session_id: str, db: Session = Depends(get_db)):
    return _step(db, _get_or_404(db, session_id), "print")


@router.patch("/{session_id}/cancel", response_model=SessionResponse)
def cancel_session(session_id: str, db: Session = Depends(get_db)):
    db_obj = _get_or_404(db, session_id)
    if db_obj.state == SessionState.CANCELLED:
        return _attach_snapshot(db_obj)
    if db_obj.state not in CANCELLABLE:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot cancel session in state '{db_obj.state}'",
        )
    db_obj.state = SessionState.CANCELLED
    device = db.get(Device, db_obj.device_id) if db_obj.device_id else None
    _write_log(db, db_obj, device, "cancelled")
    try:
        enqueue(db, "sessions", db_obj.id)
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(db_obj)
    return _attach_snapshot(db_obj)
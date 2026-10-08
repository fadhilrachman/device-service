from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from database import get_db
from lib.device_conflict import device_conflict
from lib.device_identity import require_request_device_id
from models.camera_profile import CameraProfile
from models.device import Device
from models.printer_profile import PrinterProfile
from schemas.plug import (
    PlugCameraPrinterRequest,
    PlugCameraPrinterResponse,
    PlugCameraProfileResponse,
    PlugPrinterProfileResponse,
)

router = APIRouter(prefix="/plug", tags=["plug"])


@router.post(
    "/camera_and_printer",
    response_model=PlugCameraPrinterResponse,
    status_code=status.HTTP_201_CREATED,
)
def plug_camera_and_printer(
    payload: PlugCameraPrinterRequest, request: Request, db: Session = Depends(get_db)
):
    """Create or update the caller device's camera/printer profiles.

    The device is taken from the Bearer token claim, never the body. Each
    provided object creates a fresh profile on first plug and updates the
    already-linked profile on re-plug; missing objects are skipped.
    ``captured_at`` is accepted but not persisted.
    """
    device = db.get(Device, require_request_device_id(db, request))
    if device is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found.")

    camera_in = payload.camera_profile
    printer_in = payload.printer_profile
    if camera_in is None and printer_in is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one of camera_profile or printer_profile is required.",
        )

    camera = None
    printer = None
    if camera_in is not None:
        camera_name = (camera_in.name or "").strip()
        if not camera_name:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="camera_profile.name is required.",
            )
        camera_data = camera_in.model_dump(exclude_unset=True, exclude={"captured_at"})
        camera_data["name"] = camera_name
        if device.camera_profile_id is not None:
            camera = db.get(CameraProfile, device.camera_profile_id)
        if camera is None:
            camera = CameraProfile(**camera_data)
            db.add(camera)
            db.flush()
            device.camera_profile_id = camera.id
        else:
            for key, value in camera_data.items():
                setattr(camera, key, value)
            db.flush()
    if printer_in is not None:
        printer_name = (printer_in.name or "").strip()
        if not printer_name:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="printer_profile.name is required.",
            )
        if device.printer_profile_id is not None:
            printer = db.get(PrinterProfile, device.printer_profile_id)
        if printer is None:
            printer = PrinterProfile(name=printer_name)
            db.add(printer)
            db.flush()
            device.printer_profile_id = printer.id
        else:
            printer.name = printer_name
            db.flush()
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise device_conflict(exc)
    db.refresh(device)
    if camera is not None:
        db.refresh(camera)
    if printer is not None:
        db.refresh(printer)
    return PlugCameraPrinterResponse(
        camera_profile=PlugCameraProfileResponse.model_validate(camera) if camera else None,
        printer_profile=PlugPrinterProfileResponse.model_validate(printer) if printer else None,
    )

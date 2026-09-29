from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from database import get_db
from lib.device_identity import require_request_device_id
from models.camera_profile import CameraProfile
from models.device import Device
from models.printer_profile import PrinterProfile
from schemas.config import CameraProfileResponse, PrinterProfileResponse
from schemas.plug import PlugCameraPrinterRequest, PlugCameraPrinterResponse

router = APIRouter(prefix="/plug", tags=["plug"])


@router.post(
    "/camera_and_printer",
    response_model=PlugCameraPrinterResponse,
    status_code=status.HTTP_201_CREATED,
)
def plug_camera_and_printer(
    payload: PlugCameraPrinterRequest, request: Request, db: Session = Depends(get_db)
):
    """Create camera/printer profiles (name only) and link them to the caller.

    The device is taken from the Bearer token claim, never the body. Each
    provided name creates a fresh profile; missing names are skipped.
    """
    device = db.get(Device, require_request_device_id(request))
    if device is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found.")

    camera_name = (payload.camera_name or "").strip() or None
    printer_name = (payload.printer_name or "").strip() or None
    if camera_name is None and printer_name is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one of camera_name or printer_name is required.",
        )

    camera = None
    printer = None
    if camera_name is not None:
        camera = CameraProfile(name=camera_name)
        db.add(camera)
        db.flush()
        device.camera_profile_id = camera.id
    if printer_name is not None:
        printer = PrinterProfile(name=printer_name)
        db.add(printer)
        db.flush()
        device.printer_profile_id = printer.id
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Camera or printer profile is already in use.",
        )
    db.refresh(device)
    if camera is not None:
        db.refresh(camera)
    if printer is not None:
        db.refresh(printer)
    return PlugCameraPrinterResponse(
        camera_profile=CameraProfileResponse.model_validate(camera) if camera else None,
        printer_profile=PrinterProfileResponse.model_validate(printer) if printer else None,
    )

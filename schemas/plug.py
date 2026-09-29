from typing import Optional

from pydantic import BaseModel, ConfigDict

from schemas.config import CameraProfileResponse, PrinterProfileResponse


class PlugCameraPrinterRequest(BaseModel):
    camera_name: Optional[str] = None
    printer_name: Optional[str] = None


class PlugCameraPrinterResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    camera_profile: Optional[CameraProfileResponse] = None
    printer_profile: Optional[PrinterProfileResponse] = None

from database import Base
from .campaign import Campaign
from .booth import Booth
from .voucher_batch import VoucherBatch
from .voucher import Voucher
from .device import Device
from .device_assignment import DeviceAssignment
from .session import SessionModel as Session
from .camera_profile import CameraProfile
from .printer_profile import PrinterProfile
from .frame_template import FrameTemplate
from .campaign_frame_template import campaign_frame_templates
from .payment import Payment
from .session_device_log import SessionDeviceLog
from .sync import SyncOutbox, SyncMarker


def import_models() -> None:
    """Ensure every model is imported and registered on Base.metadata."""
    return None
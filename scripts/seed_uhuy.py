"""Seed payment-test data for Device Uhuy against the shared (Neon) database.

Target device (pre-registered, from env):
    DEVICE_ID    157141ca-3742-4694-975a-1a92826ea6d1
    DEVICE_CODE  213123
    DEVICE_NAME  Device Uhuy

Creates (idempotent, safe to re-run): campaign (with price, required by
POST /payments amount derivation), booth, camera + printer profiles (linked
only when the device has none), one active assignment, and 3 started sessions.

Never touches tenant_id / device_code_sso on the device row.

Run from the project root:  python scripts/seed_uhuy.py
"""

import sys
import uuid
from datetime import datetime
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from sqlalchemy.dialects.postgresql import insert as pg_insert  # noqa: E402

import config  # noqa: E402  (reads .env)
from database import remote_session  # noqa: E402
from lib.time import wib_now  # noqa: E402
from models.booth import Booth  # noqa: E402
from models.campaign import Campaign  # noqa: E402
from models.camera_profile import CameraProfile  # noqa: E402
from models.device import Device  # noqa: E402
from models.device_assignment import DeviceAssignment  # noqa: E402
from models.printer_profile import PrinterProfile  # noqa: E402
from models.session import SessionModel  # noqa: E402

DEVICE_ID = "157141ca-3742-4694-975a-1a92826ea6d1"
DEVICE_CODE = "213123"
DEVICE_NAME = "Device Uhuy"

_NS = uuid.NAMESPACE_URL


def sid(name: str) -> str:
    return str(uuid.uuid5(_NS, f"ourlilphotobooth/seed-uhuy/{name}"))


CAMPAIGN_ID = sid("campaign")
BOOTH_ID = sid("booth")
CAMERA_ID = sid("camera")
PRINTER_ID = sid("printer")
ASSIGNMENT_ID = sid("assignment")
SESSION_IDS = [sid(f"session-{i}") for i in (1, 2, 3)]

CAMPAIGN_PRICE = 45000


def _upsert(session, model, values: dict) -> None:
    """Upsert touching ONLY the given columns (never tenant_id/device_code_sso)."""
    table = model.__table__
    pk = [c.name for c in table.primary_key]
    stmt = pg_insert(table).values(**values)
    update_keys = [k for k in values if k not in pk]
    if update_keys:
        stmt = stmt.on_conflict_do_update(
            index_elements=pk,
            set_={k: getattr(stmt.excluded, k) for k in update_keys},
        )
    else:
        stmt = stmt.on_conflict_do_nothing(index_elements=pk)
    session.execute(stmt)


def seed_all() -> dict:
    with remote_session() as r:
        # 0. Device must exist (pre-registered). Create-or-sync identity only.
        dev = r.get(Device, DEVICE_ID)
        if dev is None:
            r.add(
                Device(
                    id=DEVICE_ID,
                    device_code=DEVICE_CODE,
                    name=DEVICE_NAME,
                    status="active",
                )
            )
            r.flush()
            dev = r.get(Device, DEVICE_ID)
            device_created = True
        else:
            dev.device_code = DEVICE_CODE
            dev.name = DEVICE_NAME
            if dev.status != "active":
                dev.status = "active"
            device_created = False

        # 1. Campaign with price (POST /payments derives amount from it).
        _upsert(
            r,
            Campaign,
            {
                "id": CAMPAIGN_ID,
                "name": "Uhuy Test Campaign",
                "status": "active",
                "price": CAMPAIGN_PRICE,
                "session_limit": 500,
                "activation_rules": {"mode": "cash_or_qr"},
            },
        )

        # 2. Booth under the campaign.
        _upsert(
            r,
            Booth,
            {
                "id": BOOTH_ID,
                "campaign_id": CAMPAIGN_ID,
                "name": "Uhuy Booth 1",
                "location": "Uhuy Venue",
                "status": "active",
            },
        )

        # 3. Profiles; link only when the device has none (one-to-one).
        _upsert(
            r,
            CameraProfile,
            {
                "id": CAMERA_ID,
                "name": "Uhuy Cam 1080p",
                "status": True,
                "resolution": "1920x1080",
                "aspect_ratio": "16:9",
                "orientation": "landscape",
                "mirror_preview": True,
                "warm_up": 30,
                "capture_timeout": 10,
            },
        )
        _upsert(
            r,
            PrinterProfile,
            {
                "id": PRINTER_ID,
                "name": "Uhuy Thermal",
                "status": True,
                "connection": "usb",
                "driver_type": "escpos",
                "transport": "usb",
                "dpi": 203,
                "width_dots": 832,
                "cut": True,
                "feed": 40,
            },
        )
        r.flush()
        dev = r.get(Device, DEVICE_ID)
        profiles_linked = []
        if dev.camera_profile_id is None:
            dev.camera_profile_id = CAMERA_ID
            profiles_linked.append("camera")
        if dev.printer_profile_id is None:
            dev.printer_profile_id = PRINTER_ID
            profiles_linked.append("printer")

        # 4. Exactly one active assignment for this device.
        for row in (
            r.query(DeviceAssignment)
            .filter(
                DeviceAssignment.device_id == DEVICE_ID,
                DeviceAssignment.status == "active",
                DeviceAssignment.id != ASSIGNMENT_ID,
            )
            .all()
        ):
            row.status = "inactive"
        _upsert(
            r,
            DeviceAssignment,
            {
                "id": ASSIGNMENT_ID,
                "booth_id": BOOTH_ID,
                "device_id": DEVICE_ID,
                "status": "active",
                "assigned_from": wib_now(),
                # Validity window is mandatory: NULL bounds are treated as
                # invalid, so the device would lose its assignment.
                "assigned_until": datetime(2030, 1, 1),
            },
        )

        # 5. Three fresh sessions ready for payment tests.
        for sess_id in SESSION_IDS:
            _upsert(
                r,
                SessionModel,
                {
                    "id": sess_id,
                    "campaign_id": CAMPAIGN_ID,
                    "booth_id": BOOTH_ID,
                    "device_id": DEVICE_ID,
                    "activation_mode": "qr",
                    "state": "started",
                    "offline": False,
                },
            )

        r.commit()

        # Verify-back.
        checks = {
            "device": r.get(Device, DEVICE_ID) is not None,
            "campaign": r.get(Campaign, CAMPAIGN_ID) is not None,
            "booth": r.get(Booth, BOOTH_ID) is not None,
            "camera": r.get(CameraProfile, CAMERA_ID) is not None,
            "printer": r.get(PrinterProfile, PRINTER_ID) is not None,
            "assignment": r.get(DeviceAssignment, ASSIGNMENT_ID) is not None,
            "sessions": sum(1 for i in SESSION_IDS if r.get(SessionModel, i) is not None),
        }

    return {
        "device_created": device_created,
        "profiles_linked": profiles_linked,
        "checks": checks,
        "ids": {
            "device": DEVICE_ID,
            "campaign": CAMPAIGN_ID,
            "booth": BOOTH_ID,
            "camera": CAMERA_ID,
            "printer": PRINTER_ID,
            "assignment": ASSIGNMENT_ID,
            "sessions": SESSION_IDS,
        },
    }


if __name__ == "__main__":
    result = seed_all()
    print(f"device {DEVICE_CODE} ({DEVICE_ID}) created={result['device_created']}")
    print(f"profiles linked this run: {result['profiles_linked'] or 'none (kept existing)'}")
    for key, value in result["checks"].items():
        print(f"  {key}: {value}")
    assert all(v if isinstance(v, bool) else v == 3 for v in result["checks"].values()), result["checks"]
    print("SEED OK")
    print("Next: sync the kiosk (restart service or wait one cycle), then")
    print('  POST /payments {"method": "QRIS"}  -> 201 amount=45000.00')

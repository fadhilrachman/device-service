"""Idempotent seed for the demo device against the shared (Neon) database.

Single source of truth for the demo device identity:

    DEVICE_ID    fixed UUID (uuid5 of "ourlilphotobooth/device/{code}")
    DEVICE_CODE  PHB-001

The same identity must be set in the device-service .env. Run from the project
root:  python scripts/seed_neon.py
"""

import os
import sys
import uuid
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

# Point the remote DB at the admin panel's database unless already set.
_BACKEND_ENV = _ROOT.parent / "backend2" / ".env"
if not os.getenv("REMOTE_DATABASE_URL") and _BACKEND_ENV.exists():
    for line in _BACKEND_ENV.read_text(encoding="utf-8").splitlines():
        if line.startswith("DATABASE_URL="):
            os.environ["REMOTE_DATABASE_URL"] = line.split("=", 1)[1].strip()
            break

import config  # noqa: E402  (reads .env)
from database import remote_session  # noqa: E402
from lib.utils import new_id  # noqa: E402
from models.booth import Booth  # noqa: E402
from models.campaign import Campaign  # noqa: E402
from models.camera_profile import CameraProfile  # noqa: E402
from models.campaign_frame_template import campaign_frame_templates  # noqa: E402
from models.device import Device  # noqa: E402
from models.device_assignment import DeviceAssignment  # noqa: E402
from models.frame_template import FrameTemplate, PublishState  # noqa: E402
from models.printer_profile import PrinterProfile  # noqa: E402
from models.voucher import Voucher  # noqa: E402
from models.voucher_batch import VoucherBatch  # noqa: E402
from sqlalchemy.dialects.postgresql import insert as pg_insert  # noqa: E402

DEVICE_CODE = config.DEVICE_CODE or "PHB-001"
DEVICE_ID = config.DEVICE_ID or str(
    uuid.uuid5(uuid.NAMESPACE_URL, f"ourlilphotobooth/device/{DEVICE_CODE}")
)

_NS = uuid.NAMESPACE_URL


def sid(name: str) -> str:
    return str(uuid.uuid5(_NS, f"ourlilphotobooth/seed/{name}"))


CAMPAIGN_ID = sid("campaign/phb-demo")
BOOTH_ID = sid("booth/phb-demo")
CAMERA_ID = sid("camera/phb-demo")
PRINTER_ID = sid("printer/phb-demo")
FRAME_PUBLIC_ID = sid("frame/phb-demo-public")
FRAME_DRAFT_ID = sid("frame/phb-demo-draft")
ASSIGNMENT_ID = sid("assignment/phb-demo")
BATCH_ID = sid("batch/phb-demo")

VOUCHER_CODES = [f"PHB-{i:04d}" for i in range(1, 6)]

CAMPAIGN_NAME = "Pesta Sweet Seventeen PHB"
BOOTH_NAME = "Booth 1 - Indoor"
CAMERA_RESOLUTION = "2560x1440"


def _upsert(session, model, values: dict) -> None:
    table = model.__table__
    pk = [c.name for c in table.primary_key]
    stmt = pg_insert(table).values(**values)
    stmt = stmt.on_conflict_do_update(
        index_elements=pk,
        set_={
            c.name: getattr(stmt.excluded, c.name)
            for c in table.columns
            if c.name not in pk
        },
    )
    session.execute(stmt)


def seed_all() -> dict:
    """Create/refresh demo config for the fixed device. Safe to run repeatedly."""
    with remote_session() as r:
        _upsert(
            r,
            Campaign,
            {
                "id": CAMPAIGN_ID,
                "name": CAMPAIGN_NAME,
                "status": "active",
                "price": 45000,
                "session_limit": 500,
                "activation_rules": {"mode": "cash_or_qr"},
            },
        )

        _upsert(
            r,
            Booth,
            {
                "id": BOOTH_ID,
                "campaign_id": CAMPAIGN_ID,
                "name": BOOTH_NAME,
                "location": "Venue Hall 1",
                "status": "active",
            },
        )

        _upsert(
            r,
            CameraProfile,
            {
                "id": CAMERA_ID,
                "name": "Webcam PHB 1080p",
                "status": True,
                "resolution": CAMERA_RESOLUTION,
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
                "name": "Thermal 203dpi PHB",
                "status": True,
                "connection": "usb",
                "driver_type": "escpos",
                "transport": "usb",
                "dpi": 203,
                "width_dots": 832,
                "max_height_dots": 2600,
                "darkness": 10,
                "speed": 18,
                "cut": True,
                "feed": 40,
            },
        )

        _upsert(
            r,
            FrameTemplate,
            {
                "id": FRAME_PUBLIC_ID,
                "name": "Frame 4x6 Star (public)",
                "version": "1.0",
                "assets": "[]",
                "aspect": "4x6",
                "dimensions": "1200x1800",
                "print_variant": "print_star.png",
                "digital_variant": "digital_star.png",
                "checksum": "seed-public-4x6-star",
                "publish_state": PublishState.PUBLIC,
            },
        )

        _upsert(
            r,
            FrameTemplate,
            {
                "id": FRAME_DRAFT_ID,
                "name": "Frame 4x6 Star (draft)",
                "version": "1.1",
                "assets": "[]",
                "aspect": "4x6",
                "dimensions": "1200x1800",
                "print_variant": "print_star_v2.png",
                "digital_variant": "digital_star_v2.png",
                "checksum": "seed-public-4x6-star-v2",
                "publish_state": PublishState.DRAFT,
            },
        )

        _upsert(
            r,
            Device,
            {
                "id": DEVICE_ID,
                "device_code": DEVICE_CODE,
                "name": f"Demo {DEVICE_CODE}",
                "serial_number": "SN-PHB-001",
                "status": "active",
                "camera_profile_id": CAMERA_ID,
                "printer_profile_id": PRINTER_ID,
                "app_version": config.APP_VERSION,
            },
        )

        _upsert(
            r,
            DeviceAssignment,
            {
                "id": ASSIGNMENT_ID,
                "booth_id": BOOTH_ID,
                "device_id": DEVICE_ID,
                "status": "active",
            },
        )

        _upsert(
            r,
            VoucherBatch,
            {
                "id": BATCH_ID,
                "campaign_id": CAMPAIGN_ID,
                "name": "Batch Offline PHB-001",
                "entitlement_rules": {"print": 1, "digital": 1},
                "offline_eligible": True,
            },
        )

        for code in VOUCHER_CODES:
            _upsert(
                r,
                Voucher,
                {
                    "id": sid(f"voucher/{code}"),
                    "batch_id": BATCH_ID,
                    "code": code,
                    "status": "available",
                },
            )

        j = campaign_frame_templates
        r.execute(
            pg_insert(j)
            .values(campaign_id=CAMPAIGN_ID, frame_template_id=FRAME_PUBLIC_ID)
            .on_conflict_do_nothing(index_elements=[j.c.campaign_id, j.c.frame_template_id])
        )
        r.commit()

    return {
        "device": DEVICE_ID,
        "device_code": DEVICE_CODE,
        "campaign": CAMPAIGN_ID,
        "booth": BOOTH_ID,
        "camera": CAMERA_ID,
        "printer": PRINTER_ID,
        "frame_public": FRAME_PUBLIC_ID,
        "frame_draft": FRAME_DRAFT_ID,
        "frame_name": "Frame 4x6 Star (public)",
        "assignment": ASSIGNMENT_ID,
        "batch": BATCH_ID,
        "codes": VOUCHER_CODES,
        "voucher_count": len(VOUCHER_CODES),
        "campaign_name": CAMPAIGN_NAME,
        "booth_name": BOOTH_NAME,
        "camera_resolution": CAMERA_RESOLUTION,
    }


if __name__ == "__main__":
    ids = seed_all()
    print(f"seeded device {ids['device_code']} ({ids['device']})")
    print(f"  campaign={ids['campaign']} booth={ids['booth']} camera={ids['camera']}")
    print(f"  vouchers={ids['voucher_count']} ({ids['codes'][0]}..{ids['codes'][-1]})")
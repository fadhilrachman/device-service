"""Tests for battery reporting via PATCH /devices/heartbeat and POST /sync/bulk.

REMOTE_DATABASE_URL points at a temp SQLite file so the suite runs without
network. The device identity comes from the Bearer token claim.
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_TMPDIR = tempfile.mkdtemp(prefix="devicesvc_batt_")
os.environ["REMOTE_DATABASE_URL"] = f"sqlite:///{os.path.join(_TMPDIR, 'device.db')}"
os.environ["PAYMENT_PROVIDER"] = "stub"
os.environ["SSO_BASE_URL"] = "http://127.0.0.1:1"

from fastapi.testclient import TestClient  # noqa: E402

from database import remote_session  # noqa: E402
from main import app  # noqa: E402
from models.camera_profile import CameraProfile  # noqa: E402
from models.device import Device  # noqa: E402

import base64  # noqa: E402
import json  # noqa: E402
import time  # noqa: E402


def _make_token(client_id: str = "TEST-BATT-0001") -> str:
    def _b64(data: dict) -> str:
        raw = json.dumps(data).encode("utf-8")
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")

    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "user_id": "test-device-1",
        "device_id": "test-device-1",
        "client_id": client_id,
        "iat": 0,
        "exp": int(time.time()) + 3600,
    }
    return f"{_b64(header)}.{_b64(payload)}.sig"


AUTH_HEADERS = {"Authorization": f"Bearer {_make_token()}"}
BARE_HEADERS = {"Authorization": f"Bearer {_make_token('TEST-BARE-0001')}"}

PASS = 0


def ok(label: str):
    global PASS
    PASS += 1
    print(f"  OK  {label}")


with TestClient(app, headers=AUTH_HEADERS) as client:
    with remote_session() as db:
        db.add(CameraProfile(id="cam-batt-1", name="Batt Cam", battery=50))
        db.add(
            Device(
                id="test-device-1",
                device_code="TEST-BATT-0001",
                name="Battery Device",
                status="active",
                camera_profile_id="cam-batt-1",
            )
        )
        db.add(
            Device(
                id="test-device-bare",
                device_code="TEST-BARE-0001",
                name="Bare Device",
                status="active",
            )
        )
        db.commit()

    # 1. Heartbeat battery lands on the linked camera_profiles row
    r = client.patch("/devices/heartbeat", json={"battery": 82})
    assert r.status_code == 200, r.text
    with remote_session() as db:
        assert db.get(CameraProfile, "cam-batt-1").battery == 82
    ok("PATCH /devices/heartbeat battery -> camera_profiles.battery")

    # 2. Out-of-range battery is a 422 naming the field
    for bad in (-1, 101):
        r = client.patch("/devices/heartbeat", json={"battery": bad})
        assert r.status_code == 422, (bad, r.text)
    with remote_session() as db:
        assert db.get(CameraProfile, "cam-batt-1").battery == 82
    ok("heartbeat battery outside 0-100 -> 422, stored value untouched")

    # 3. Legacy camera_health is accepted but ignored (no deny)
    r = client.patch("/devices/heartbeat", json={"camera_health": "ok"})
    assert r.status_code == 200, r.text
    with remote_session() as db:
        dev = db.get(Device, "test-device-1")
        assert dev.camera_health is None, dev.camera_health
        assert db.get(CameraProfile, "cam-batt-1").battery == 82
    ok("legacy camera_health on heartbeat -> 200 and ignored")

    # 4. Battery with no linked camera profile is a 404
    r = client.patch("/devices/heartbeat", json={"battery": 70}, headers=BARE_HEADERS)
    assert r.status_code == 404, r.text
    ok("heartbeat battery without linked camera -> 404")

    # 5. Bulk sync battery updates the camera row and reports device_updated
    r = client.post("/sync/bulk", json={"device": {"battery": 64}})
    assert r.status_code == 201, r.text
    assert r.json()["device_updated"] is True, r.text
    with remote_session() as db:
        assert db.get(CameraProfile, "cam-batt-1").battery == 64
    ok("POST /sync/bulk battery -> camera row + device_updated True")

    # 6. Bulk battery out of range is a 422
    r = client.post("/sync/bulk", json={"device": {"battery": 120}})
    assert r.status_code == 422, r.text
    ok("bulk battery outside 0-100 -> 422")

    # 7. Bulk battery without a linked camera is a 404
    r = client.post(
        "/sync/bulk", json={"device": {"battery": 70}}, headers=BARE_HEADERS
    )
    assert r.status_code == 404, r.text
    ok("bulk battery without linked camera -> 404")

    # 8. Legacy camera_health in bulk is accepted but ignored
    r = client.post("/sync/bulk", json={"device": {"camera_health": "connect"}})
    assert r.status_code == 201, r.text
    with remote_session() as db:
        assert db.get(Device, "test-device-1").camera_health is None
        assert db.get(CameraProfile, "cam-batt-1").battery == 64
    ok("legacy camera_health in bulk -> accepted and ignored")

print(f"\nALL {PASS} battery tests passed ({_TMPDIR})")

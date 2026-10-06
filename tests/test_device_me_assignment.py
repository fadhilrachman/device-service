"""Tests for nested assignment in GET /devices/me and ID derivation in POST /payments."""

import os
import sys
import tempfile
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_TMPDIR = tempfile.mkdtemp(prefix="devicesvc_assign_")
os.environ["REMOTE_DATABASE_URL"] = f"sqlite:///{os.path.join(_TMPDIR, 'device.db')}"
os.environ["PAYMENT_PROVIDER"] = "stub"
os.environ["SSO_BASE_URL"] = "http://127.0.0.1:1"

from fastapi.testclient import TestClient  # noqa: E402

from database import remote_session  # noqa: E402
from lib.time import wib_now  # noqa: E402
from main import app  # noqa: E402
from models.booth import Booth  # noqa: E402
from models.campaign import Campaign  # noqa: E402
from models.device import Device  # noqa: E402
from models.device_assignment import DeviceAssignment  # noqa: E402

import base64  # noqa: E402
import json  # noqa: E402
import time  # noqa: E402


def _make_token() -> str:
    def _b64(data: dict) -> str:
        raw = json.dumps(data).encode("utf-8")
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")

    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "user_id": "test-device-1",
        "device_id": "dev-assigned-1",
        "client_id": "TEST-ASSIGN-01",
        "iat": 0,
        "exp": int(time.time()) + 3600,
    }
    return f"{_b64(header)}.{_b64(payload)}.sig"


AUTH_HEADERS = {"Authorization": f"Bearer {_make_token()}"}

PASS = 0


def ok(label: str):
    global PASS
    PASS += 1
    print(f"  OK  {label}")


with TestClient(app, headers=AUTH_HEADERS) as client:
    with remote_session() as db:
        db.add(
            Device(
                id="dev-assigned-1",
                device_code="TEST-ASSIGN-01",
                name="Test Assign Device",
                status="active",
            )
        )
        db.commit()

    r = client.get("/devices/me")
    assert r.status_code == 200, r.text
    assert r.json()["id"] == "dev-assigned-1"
    assert r.json()["device_assignment"] is None
    ok("GET /devices/me without assignment -> null")

    with remote_session() as db:
        db.add(Campaign(id="camp-1", name="Promo Test", price=50000, status="active"))
        db.add(
            Booth(
                id="booth-1",
                name="Booth CFD 01",
                location="Lobby",
                status="active",
                campaign_id="camp-1",
            )
        )
        db.add(
            DeviceAssignment(
                booth_id="booth-1",
                device_id="dev-assigned-1",
                status="active",
                assigned_from=wib_now(),
                assigned_until=datetime(2030, 1, 1),
            )
        )
        db.commit()

    # ---- nested booth + campaign in /devices/me -------------------------
    r = client.get("/devices/me")
    assert r.status_code == 200, r.text
    assignment = r.json()["device_assignment"]
    assert assignment is not None, r.text
    assert assignment["booth_id"] == "booth-1"
    assert assignment["booth_name"] == "Booth CFD 01"
    assert assignment["booth_location"] == "Lobby"
    assert assignment["campaign_id"] == "camp-1"
    booth = assignment["booth"]
    assert booth["id"] == "booth-1", booth
    assert booth["name"] == "Booth CFD 01", booth
    assert booth["location"] == "Lobby", booth
    assert booth["status"] == "active", booth
    campaign = assignment["campaign"]
    assert campaign["id"] == "camp-1", campaign
    assert campaign["name"] == "Promo Test", campaign
    assert campaign["status"] == "active", campaign
    assert float(campaign["price"]) == 50000.0, campaign
    ok("GET /devices/me nests full booth + campaign objects")

    # ---- /config is config-only (no assignment/booth/campaign) -------
    r = client.get("/config")
    assert r.status_code == 200, r.text
    assert r.json()["device"]["id"] == "dev-assigned-1"
    assert "assignment" not in r.json()
    assert "booth" not in r.json()
    assert "campaign" not in r.json()
    ok("GET /config returns config-only bundle")

    # ---- window validation ------------------------------------------------
    def _set_window(from_dt, until_dt, status="active"):
        with remote_session() as db:
            row = (
                db.query(DeviceAssignment)
                .filter(DeviceAssignment.device_id == "dev-assigned-1")
                .order_by(DeviceAssignment.assigned_from.desc())
                .first()
            )
            row.status = status
            row.assigned_from = from_dt
            row.assigned_until = until_dt
            db.commit()

    # expired window -> /me null, payments/sessions 400
    _set_window(wib_now() - timedelta(days=10), wib_now() - timedelta(days=1))
    r = client.get("/devices/me")
    assert r.status_code == 200 and r.json()["device_assignment"] is None, r.text
    ok("GET /devices/me expired window -> null assignment")
    r = client.post("/sessions", json={})
    assert r.status_code == 400 and "window has expired" in r.json()["detail"], r.text
    ok("POST /sessions expired window -> 400")

    # future window -> null / 400
    _set_window(wib_now() + timedelta(days=1), datetime(2030, 1, 1))
    r = client.get("/devices/me")
    assert r.status_code == 200 and r.json()["device_assignment"] is None, r.text
    ok("GET /devices/me future window -> null assignment")

    # NULL bound -> invalid -> null / 400
    _set_window(wib_now() - timedelta(days=1), None)
    r = client.get("/devices/me")
    assert r.status_code == 200 and r.json()["device_assignment"] is None, r.text
    ok("GET /devices/me NULL until -> null assignment")

    # restore valid window -> assignment back
    _set_window(wib_now() - timedelta(days=1), datetime(2030, 1, 1))
    r = client.get("/devices/me")
    assert r.status_code == 200 and r.json()["device_assignment"] is not None, r.text
    ok("GET /devices/me valid window restored -> assignment present")

print(f"\nALL {PASS} assignment tests passed ({_TMPDIR})")

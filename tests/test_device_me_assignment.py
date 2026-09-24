"""Tests for nested assignment in GET /devices/me and ID derivation in POST /payments."""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_TMPDIR = tempfile.mkdtemp(prefix="devicesvc_assign_")
os.environ["REMOTE_DATABASE_URL"] = "postgresql://invalid:invalid@localhost:1/offline"
os.environ["LOCAL_DB_PATH"] = os.path.join(_TMPDIR, "device.db")
os.environ["DEVICE_ID"] = "dev-assigned-1"
os.environ["DEVICE_CODE"] = "TEST-ASSIGN-01"
os.environ["DEVICE_NAME"] = "Test Assign Device"
os.environ["SYNC_ON_STARTUP"] = "false"
os.environ["SSO_BASE_URL"] = "http://127.0.0.1:1"

from fastapi.testclient import TestClient  # noqa: E402

from database import local_session  # noqa: E402
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
    payload = {"user_id": "test-device-1", "iat": 0, "exp": int(time.time()) + 3600}
    return f"{_b64(header)}.{_b64(payload)}.sig"


AUTH_HEADERS = {"Authorization": f"Bearer {_make_token()}"}

PASS = 0


def ok(label: str):
    global PASS
    PASS += 1
    print(f"  OK  {label}")


with TestClient(app, headers=AUTH_HEADERS) as client:
    r = client.get("/devices/me")
    assert r.status_code == 200, r.text
    assert r.json()["id"] == "dev-assigned-1"
    assert r.json()["device_assignment"] is None
    ok("GET /devices/me without assignment -> null")

    with local_session() as db:
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
            Booth(id="booth-2", name="Booth Tanpa Kampanye", status="active")
        )
        db.add(Campaign(id="camp-2", name="Paket Override", price=75000, status="active"))
        db.add(
            DeviceAssignment(
                booth_id="booth-1",
                device_id="dev-assigned-1",
                status="active",
                assigned_from=wib_now(),
            )
        )
        # Second device with no assignment at all.
        db.add(Device(id="dev-lonely-1", device_code="TEST-LONELY-01", name="Lonely"))
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

    # ---- /config still works after schema move (re-export intact) -------
    r = client.get("/config")
    assert r.status_code == 200, r.text
    assert r.json()["device"]["id"] == "dev-assigned-1"
    ok("GET /config unaffected by schema move")

    # ---- POST /payments with only {"method"} (full derivation) ----------
    r = client.post("/payments", json={"method": "QRIS"})
    assert r.status_code == 201, r.text
    payment = r.json()["payment"]
    assert payment["device_id"] == "dev-assigned-1", payment
    assert payment["booth_id"] == "booth-1", payment
    assert payment["campaign_id"] == "camp-1", payment
    assert float(payment["amount"]) == 50000.0, payment
    assert payment["provider"] == "stub"
    ok("POST /payments minimal payload derives device/booth/campaign/amount")

    # ---- explicit booth override wins ------------------------------------
    r = client.post(
        "/payments",
        json={"booth_id": "booth-2", "amount": 10000, "method": "cash"},
    )
    assert r.status_code == 201, r.text
    payment = r.json()["payment"]
    assert payment["booth_id"] == "booth-2", payment
    assert payment["campaign_id"] is None, payment
    assert float(payment["amount"]) == 10000.0, payment
    ok("POST /payments explicit booth_id overrides assignment")

    # ---- explicit campaign override wins ---------------------------------
    r = client.post("/payments", json={"campaign_id": "camp-2", "method": "cash"})
    assert r.status_code == 201, r.text
    payment = r.json()["payment"]
    assert payment["booth_id"] == "booth-1", payment
    assert payment["campaign_id"] == "camp-2", payment
    assert float(payment["amount"]) == 75000.0, payment
    ok("POST /payments explicit campaign_id overrides booth campaign")

    # ---- device without assignment and without booth_id -> 400 -----------
    r = client.post(
        "/payments",
        json={"device_id": "dev-lonely-1", "amount": 5000, "method": "cash"},
    )
    assert r.status_code == 400, r.text
    assert "not assigned" in r.json()["detail"], r.text
    ok("POST /payments unassigned device without booth_id -> 400")

    # ---- unknown explicit booth still 404 --------------------------------
    r = client.post(
        "/payments",
        json={"booth_id": "does-not-exist", "amount": 5000},
    )
    assert r.status_code == 404, r.text
    ok("POST /payments unknown booth_id -> 404")

print(f"\nALL {PASS} assignment tests passed ({_TMPDIR})")

"""Smoke test for the device service (direct remote DB, no sync layer).

REMOTE_DATABASE_URL points at a temp SQLite file so the suite runs without
network. All reads/writes go straight to that database.
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_TMPDIR = tempfile.mkdtemp(prefix="devicesvc_")
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
from models.frame_template import FrameTemplate, PublishState  # noqa: E402
from models.voucher import Voucher  # noqa: E402
from models.voucher_batch import VoucherBatch  # noqa: E402

import base64  # noqa: E402
import json  # noqa: E402
import time  # noqa: E402


def _make_token(user_id: str = "test-device-1", device_id: str = "test-device-1") -> str:
    """Mint a structurally valid HS256-style JWT accepted by ProtectTokenMiddleware."""
    def _b64(data: dict) -> str:
        raw = json.dumps(data).encode("utf-8")
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "user_id": user_id,
        "device_id": device_id,
        "iat": 0,
        "exp": int(time.time()) + 3600,
    }
    return f"{_b64(header)}.{_b64(payload)}.sig"


def _make_token_no_device(user_id: str = "test-device-1") -> str:
    def _b64(data: dict) -> str:
        raw = json.dumps(data).encode("utf-8")
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {"user_id": user_id, "iat": 0, "exp": int(time.time()) + 3600}
    return f"{_b64(header)}.{_b64(payload)}.sig"


AUTH_HEADERS = {"Authorization": f"Bearer {_make_token()}"}

PASS = 0


def ok(label: str):
    global PASS
    PASS += 1
    print(f"  OK  {label}")


with TestClient(app, headers=AUTH_HEADERS) as client:
    # seed the pre-registered device (no auto-provisioning anymore) plus a
    # valid assignment window (sessions/payments require one)
    from datetime import datetime, timedelta

    with remote_session() as db:
        db.add(
            Device(
                id="test-device-1",
                device_code="TEST-DEV-0001",
                name="Test Device",
                status="active",
            )
        )
        db.add(Campaign(id="camp-smoke", name="Smoke Campaign", price=50000))
        db.add(
            Booth(
                id="booth-smoke",
                name="Smoke Booth",
                status="active",
                campaign_id="camp-smoke",
            )
        )
        db.add(
            DeviceAssignment(
                booth_id="booth-smoke",
                device_id="test-device-1",
                status="active",
                assigned_from=wib_now() - timedelta(days=1),
                assigned_until=datetime(2030, 1, 1),
            )
        )
        db.commit()

    # 1. Health
    r = client.get("/")
    assert r.status_code == 200 and "running" in r.json()["message"]
    ok("GET / health")

    # 2. Device identity
    r = client.get("/devices/me")
    assert r.status_code == 200
    me = r.json()
    assert me["device_code"] == "TEST-DEV-0001"
    assert me["status"] == "active"
    ok("GET /devices/me")

    # token without device_id claim -> 401 (identity comes from the token)
    r = client.get(
        "/devices/me",
        headers={"Authorization": f"Bearer {_make_token_no_device()}"},
    )
    assert r.status_code == 401 and "device_id" in r.json()["detail"], r.text
    ok("GET /devices/me without device_id claim -> 401")

    # token device_id that is not registered -> 404
    r = client.get(
        "/devices/me",
        headers={"Authorization": f"Bearer {_make_token('ghost', 'ghost-device')}"},
    )
    assert r.status_code == 404, r.text
    ok("GET /devices/me unregistered token device -> 404")

    # 3. Heartbeat
    r = client.patch("/devices/heartbeat", json={"storage_state": "ok", "camera_health": "ok"})
    assert r.status_code == 200
    heartbeat = r.json()
    assert heartbeat["connectivity"] == "online"
    assert heartbeat["storage_state"] == "ok"
    ok("PATCH /devices/heartbeat (online)")

    # 4. Empty config bundle (config-only: no assignment/booth/campaign keys)
    r = client.get("/config")
    assert r.status_code == 200
    cfg = r.json()
    assert cfg["device"]["id"] == me["id"]
    assert cfg["frames"] == [] and cfg["offline_vouchers"] == 0
    assert "assignment" not in cfg and "booth" not in cfg and "campaign" not in cfg
    assert set(cfg) == {
        "device",
        "camera_profile",
        "printer_profile",
        "frames",
        "offline_vouchers",
    }, set(cfg)
    ok("GET /config (config-only, empty)")

    # template list (empty)
    r = client.get("/templates")
    assert r.status_code == 200
    assert r.json() == []
    ok("GET /templates (empty)")

    r = client.get("/config/campaign")
    assert r.status_code == 200 and r.json()["frame_set"] == [], r.text
    ok("GET /config/campaign has an empty frame_set before linking frames")

    with remote_session() as db:
        db.add(FrameTemplate(
            id="frame-public-1",
            name="Public Frame",
            version="1",
            assets="",
            aspect="4:5",
            dimensions="",
            safe_area="",
            transforms={"slots": [{"x": 10, "y": 20}]},
            preview_variant="1 foto",
            print_variant="",
            digital_variant="",
            checksum="frame-checksum",
            compatibility="",
            publish_state=PublishState.PUBLIC,
        ))
        db.add(FrameTemplate(
            id="frame-public-2",
            name="Unlinked Public Frame",
            version="1",
            assets="",
            aspect="4:5",
            dimensions="",
            safe_area="",
            transforms={"slots": [{"x": 30, "y": 40}]},
            preview_variant="1 foto",
            print_variant="",
            digital_variant="",
            checksum="unlinked-frame-checksum",
            compatibility="",
            publish_state=PublishState.PUBLIC,
        ))
        db.add(FrameTemplate(
            id="frame-draft-1",
            name="Draft Frame",
            version="1",
            assets="",
            aspect="4:5",
            dimensions="",
            safe_area="",
            transforms={},
            preview_variant="1 foto",
            print_variant="",
            digital_variant="",
            checksum="draft-frame-checksum",
            compatibility="",
            publish_state=PublishState.DRAFT,
        ))
        db.commit()

    templates = client.get("/templates")
    config = client.get("/config")
    assert templates.status_code == 200 and config.status_code == 200
    assert config.json()["frames"] == templates.json()
    assert len(templates.json()) == 2
    ok("GET /config.frames matches /templates with global public frames")

    with remote_session() as db:
        campaign = db.get(Campaign, "camp-smoke")
        campaign.frame_templates.append(db.get(FrameTemplate, "frame-public-1"))
        campaign.frame_templates.append(db.get(FrameTemplate, "frame-draft-1"))
        db.commit()

    templates = client.get("/templates")
    config = client.get("/config")
    assert templates.status_code == 200 and config.status_code == 200
    assert config.json()["frames"] == templates.json()
    assert [frame["id"] for frame in templates.json()] == ["frame-public-1"]
    assert templates.json()[0]["transforms"] == {"slots": [{"x": 10, "y": 20}]}
    assert templates.json()[0]["publish_state"] == "public"
    ok("GET /config.frames matches campaign templates exactly")

    r = client.get("/config/campaign")
    assert r.status_code == 200, r.text
    assert r.json()["frame_set"] == ["frame-draft-1", "frame-public-1"]
    ok("GET /config/campaign frame_set lists linked frames in a stable order")

    # 5. Start a session (direct write, offline flag comes from the client)
    r = client.post("/sessions", json={})
    assert r.status_code == 201, r.text
    session = r.json()
    assert session["state"] == "started"
    assert session["offline"] is False
    assert session["device_code"] == "TEST-DEV-0001"
    sid = session["id"]
    ok("POST /sessions")

    r = client.post("/sessions", json={"offline": True})
    assert r.status_code == 201 and r.json()["offline"] is True
    ok("POST /sessions with client offline flag")

    # session list is scoped to this device
    r = client.get("/sessions")
    assert r.status_code == 200 and r.json()["data"][0]["device_id"] == "test-device-1"
    ok("GET /sessions list (device-scoped)")

    r = client.get(f"/sessions/{sid}")
    assert r.status_code == 200 and r.json()["id"] == sid
    ok("GET /sessions/{id}")

    # update session state
    r = client.patch(f"/sessions/{sid}", json={"state": "complete"})
    assert r.status_code == 200 and r.json()["state"] == "complete"
    ok("PATCH /sessions/{id} state")

    # ---- lifecycle state machine --------------------------------------
    r = client.post("/sessions", json={})
    assert r.status_code == 201 and r.json()["state"] == "started"
    lc = r.json()["id"]

    r = client.patch(f"/sessions/{lc}", json={"state": "simulation"})
    assert r.status_code == 200 and r.json()["state"] == "simulation", r.text
    ok("PATCH /sessions/{id} state -> simulation")

    r = client.patch(f"/sessions/{lc}/simulation")
    assert r.status_code == 200 and r.json()["state"] == "take_photo", r.text
    r = client.patch(f"/sessions/{lc}/retake")
    assert r.status_code == 200 and r.json()["state"] == "re_take", r.text
    r = client.patch(f"/sessions/{lc}/photo")
    assert r.status_code == 200 and r.json()["state"] == "take_photo", r.text
    r = client.patch(f"/sessions/{lc}/print")
    assert r.status_code == 200 and r.json()["state"] == "print", r.text
    ok("PATCH /{id}/simulation/retake/photo/print")

    r = client.patch(f"/sessions/{lc}", json={"state": "complete"})
    assert r.status_code == 200 and r.json()["state"] == "complete", r.text
    ok("PATCH /sessions/{id} state -> complete")

    # invalid transition -> 409
    r = client.patch(f"/sessions/{lc}/simulation")
    assert r.status_code == 409
    ok("invalid lifecycle transition -> 409")

    # unknown session action target -> 404
    r = client.patch("/sessions/does-not-exist/simulation")
    assert r.status_code == 404
    ok("lifecycle target missing -> 404")

    # cancel from non-terminal state
    r = client.post("/sessions", json={})
    cid = r.json()["id"]
    r = client.patch(f"/sessions/{cid}/cancel")
    assert r.status_code == 200 and r.json()["state"] == "cancelled", r.text
    ok("PATCH /sessions/{id}/cancel")

    # frame not in campaign (empty config) -> 400
    r = client.post(
        "/sessions",
        json={"frame_template_id": "nope"},
    )
    assert r.status_code == 400, r.text
    ok("frame_template_id rejected when not in campaign (400)")

    # 6. Voucher flow
    device_id = me["id"]
    with remote_session() as db:
        batch = VoucherBatch(name="Offline Batch", offline_eligible=True)
        db.add(batch)
        db.flush()
        v = Voucher(batch_id=batch.id, code="TEST-AAAA")
        db.add(v)
        db.commit()

    # assignment valid but no vouchers yet -> empty list
    r = client.get("/vouchers")
    assert r.status_code == 200 and r.json() == [], r.text
    assert client.get("/config").json()["offline_vouchers"] == 0
    ok("GET /vouchers empty -> []")

    # new session to redeem against
    r = client.post("/sessions", json={})
    sid2 = r.json()["id"]

    r = client.post("/vouchers/TEST-AAAA/redeem", json={"session_id": sid2})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "available"
    assert r.json()["session_id"] is None
    ok("POST /vouchers/{code}/redeem verifies voucher (no consume)")

    # repeated verify is idempotent (voucher never consumed)
    r = client.post("/vouchers/TEST-AAAA/redeem", json={"session_id": sid2})
    assert r.status_code == 200
    ok("voucher verify repeated (idempotent)")

    # 7. Payment flow (assignment was seeded up front with a valid window)
    r = client.post(
        "/payments",
        json={"session_id": sid, "amount": 50000, "method": "QRIS"},
    )
    assert r.status_code == 201, r.text
    payment = r.json()["payment"]
    assert payment["status"] == "pending"
    assert payment["booth_id"] == "booth-smoke", payment
    assert payment["campaign_id"] == "camp-smoke", payment
    assert payment["provider_ref"].startswith("stub-")
    assert "mock-pay" in r.json()["charge_url"]
    ok("POST /payments (stub)")

    r = client.get(f"/payments/{payment['id']}")
    assert r.status_code == 200 and r.json()["id"] == payment["id"]
    ok("GET /payments/{id}")

    # 8. Voucher list: batch.campaign_id == active campaign AND device_id == device
    with remote_session() as db:
        db.add(Campaign(id="camp-other", name="Other Campaign", price=1000))
        db.add(
            Booth(
                id="booth-other",
                name="Other Booth",
                status="active",
                campaign_id="camp-other",
            )
        )
        batch_mine = VoucherBatch(
            campaign_id="camp-smoke", name="Smoke Batch", offline_eligible=True
        )
        batch_other = VoucherBatch(
            campaign_id="camp-other", name="Other Batch", offline_eligible=True
        )
        batch_legacy = VoucherBatch(
            campaign_id="camp-smoke", name="Legacy Flag Batch", offline_eligible=False
        )
        db.add(batch_mine)
        db.add(batch_other)
        db.add(batch_legacy)
        db.flush()
        db.add(Voucher(batch_id=batch_mine.id, code="MINE-0001", device_id=device_id))
        db.add(Voucher(batch_id=batch_mine.id, code="MINE-USED", device_id=device_id, status="used"))
        db.add(Voucher(batch_id=batch_legacy.id, code="MINE-LEGACY", device_id=device_id))
        db.add(Voucher(batch_id=batch_mine.id, code="OTHER-DEV", device_id="someone-else"))
        db.add(Voucher(batch_id=batch_mine.id, code="UNCLAIMED"))
        db.add(Voucher(batch_id=batch_other.id, code="OTHER-CAMP", device_id=device_id))
        db.commit()

    r = client.get("/vouchers")
    assert r.status_code == 200, r.text
    codes = sorted(v["code"] for v in r.json())
    assert codes == ["MINE-0001", "MINE-LEGACY", "MINE-USED"], codes
    available = [v for v in r.json() if v["status"] == "available"]
    assert sorted(v["code"] for v in available) == ["MINE-0001", "MINE-LEGACY"]
    assert client.get("/config").json()["offline_vouchers"] == len(available)
    first_page = client.get("/vouchers?limit=1&offset=0").json()
    second_page = client.get("/vouchers?limit=1&offset=1").json()
    assert len(first_page) == len(second_page) == 1
    assert first_page[0]["id"] != second_page[0]["id"]
    ok("GET /config.offline_vouchers matches available vouchers regardless of legacy flag")

    # 9. Device authorization API (/auth/device/*) proxies to SSO
    r = client.get("/openapi.json")
    openapi = r.json()
    for path in [
        "/auth/device/authorize/",
        "/auth/device/verification/",
        "/auth/device/token/",
        "/auth/device/refresh/",
        "/auth/device/revoke/",
    ]:
        assert path in openapi["paths"], path
    assert "/sync/status" not in openapi["paths"]
    assert "/sync/trigger" not in openapi["paths"]
    assert "/sync/bulk" in openapi["paths"]
    assert not any(path.startswith("/sessions") for path in openapi["paths"])
    assert "/vouchers/{code}" not in openapi["paths"]
    assert "/vouchers" in openapi["paths"]
    ok("OpenAPI shows /sync/bulk and hides all /sessions paths")

    # authorized operator call reaches the proxy; SSO unreachable -> 502
    r = client.post(
        "/auth/device/verification/",
        json={
            "user_code": "ABCD-EFGH",
            "organization_id": "12345678-1234-4123-8234-123456789012",
            "action": "approve",
        },
    )
    assert r.status_code == 502 and "unreachable" in r.json()["detail"], r.text
    ok("POST /auth/device/verification/ with token proxies to SSO (502)")

with TestClient(app) as client_no_auth:
    # operator-only endpoints reject requests without a Bearer token
    r = client_no_auth.post(
        "/auth/device/revoke/",
        json={"device_id": "12345678-1234-4123-8234-123456789012"},
    )
    assert r.status_code == 401
    ok("POST /auth/device/revoke/ without token -> 401 (operator-only)")

    r = client_no_auth.post(
        "/auth/device/verification/",
        json={
            "user_code": "ABCD-EFGH",
            "organization_id": "12345678-1234-4123-8234-123456789012",
            "action": "approve",
        },
    )
    assert r.status_code == 401
    ok("POST /auth/device/verification/ without token -> 401 (operator-only)")

    # docs/swagger UI must not require a token
    r = client_no_auth.get("/swagger")
    assert r.status_code != 401
    ok("GET /swagger without token passes middleware (public)")

    # onboarding endpoints are public (kiosk has no token yet): reach the proxy
    r = client_no_auth.post(
        "/auth/device/token/",
        json={
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            "device_code": "opaque-device-code",
        },
    )
    assert r.status_code != 401
    assert r.status_code == 502  # SSO unreachable
    ok("POST /auth/device/token/ without token passes middleware (public)")

    r = client_no_auth.post(
        "/auth/device/refresh/",
        json={"refresh_token": "opaque-refresh-token"},
    )
    assert r.status_code != 401
    assert r.status_code == 502
    ok("POST /auth/device/refresh/ without token passes middleware (public)")

print(f"\nALL {PASS} smoke tests passed ({_TMPDIR})")

"""Smoke test for the device service (offline-first, no real server needed)."""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_TMPDIR = tempfile.mkdtemp(prefix="devicesvc_")
os.environ["REMOTE_DATABASE_URL"] = "postgresql://invalid:invalid@localhost:1/offline"
os.environ["LOCAL_DB_PATH"] = os.path.join(_TMPDIR, "device.db")
os.environ["DEVICE_CODE"] = "TEST-DEV-0001"
os.environ["DEVICE_NAME"] = "Test Device"
os.environ["SYNC_ON_STARTUP"] = "false"

from fastapi.testclient import TestClient  # noqa: E402

from database import local_session  # noqa: E402
from main import app  # noqa: E402
from models.sync import SyncOutbox  # noqa: E402
from models.voucher import Voucher  # noqa: E402
from models.voucher_batch import VoucherBatch  # noqa: E402

PASS = 0


def ok(label: str):
    global PASS
    PASS += 1
    print(f"  OK  {label}")


with TestClient(app) as client:
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
    ok("GET /devices/me (auto-provisioned)")

    # 3. Heartbeat
    r = client.patch("/devices/heartbeat", json={"storage_state": "ok", "camera_health": "ok"})
    assert r.status_code == 200
    heartbeat = r.json()
    assert heartbeat["connectivity"] == "offline"
    assert heartbeat["storage_state"] == "ok"
    ok("PATCH /devices/heartbeat (offline)")

    # 4. Empty config bundle
    r = client.get("/config")
    assert r.status_code == 200
    cfg = r.json()
    assert cfg["device"]["id"] == me["id"]
    assert cfg["frames"] == [] and cfg["offline_vouchers"] == 0
    ok("GET /config (empty, offline)")

    # template list (empty offline)
    r = client.get("/templates")
    assert r.status_code == 200
    assert r.json() == []
    ok("GET /templates (empty, offline)")

    # 5. Start a session offline
    r = client.post("/sessions", json={})
    assert r.status_code == 201, r.text
    session = r.json()
    assert session["state"] == "started"
    assert session["offline"] is True
    assert session["device_code"] == "TEST-DEV-0001"
    sid = session["id"]
    ok("POST /sessions (offline-first)")

    # session list + get
    r = client.get("/sessions")
    assert r.status_code == 200 and r.json()["data"][0]["id"] == sid
    ok("GET /sessions list")
    r = client.get(f"/sessions/{sid}")
    assert r.status_code == 200 and r.json()["id"] == sid
    ok("GET /sessions/{id}")

    # update session state
    r = client.patch(f"/sessions/{sid}", json={"state": "complete"})
    assert r.status_code == 200 and r.json()["state"] == "complete"
    ok("PATCH /sessions/{id} state")

    # ---- lifecycle state machine (offline) ------------------------------
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

    # frame not in campaign (offline config empty) -> 400
    r = client.post(
        "/sessions",
        json={"frame_template_id": "nope"},
    )
    assert r.status_code == 400, r.text
    ok("frame_template_id rejected when not in campaign (400)")

    # 6. Voucher flow (offline-eligible batch)
    device_id = me["id"]
    with local_session() as db:
        batch = VoucherBatch(name="Offline Batch", offline_eligible=True)
        db.add(batch)
        db.flush()
        v = Voucher(batch_id=batch.id, code="TEST-AAAA")
        db.add(v)
        db.commit()

    r = client.get("/vouchers/TEST-AAAA")
    assert r.status_code == 200
    assert r.json()["status"] == "available"
    assert r.json()["offline_eligible"] is True
    ok("GET /vouchers/{code} validation")

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

    # non-eligible batch: eligibility no longer checked by verify endpoint
    with local_session() as db:
        batch2 = VoucherBatch(name="Online Only", offline_eligible=False)
        db.add(batch2)
        db.flush()
        db.add(Voucher(batch_id=batch2.id, code="TEST-BBBB"))
        db.commit()
    r = client.post("/vouchers/TEST-BBBB/redeem", json={"session_id": sid2})
    assert r.status_code == 200, r.text
    ok("voucher verify ignores offline_eligible (200)")

    # 7. Payment flow offline
    r = client.post(
        "/payments",
        json={"session_id": sid, "device_id": device_id, "amount": 50000, "method": "QRIS"},
    )
    assert r.status_code == 201, r.text
    payment = r.json()["payment"]
    assert payment["status"] == "pending"
    assert payment["provider_ref"].startswith("stub-")
    assert "mock-pay" in r.json()["charge_url"]
    ok("POST /payments (offline-first)")

    r = client.get(f"/payments/{payment['id']}")
    assert r.status_code == 200 and r.json()["id"] == payment["id"]
    ok("GET /payments/{id}")

    # 8. Sync status shows pending outbox & offline
    r = client.get("/sync/status")
    st = r.json()
    assert st["online"] is False
    assert st["pending_push"] >= 4  # 2 sessions + 1 log + 1 voucher + 1 payment etc.
    assert st["device_id"] == me["id"]
    ok("GET /sync/status (offline, pending queue)")

    r = client.post("/sync/trigger")
    assert r.status_code == 200
    assert r.json()["ok"] is False and r.json()["error"] == "offline"
    ok("POST /sync/trigger (offline -> reports offline)")

    # 9. Invalid voucher -> 404
    r = client.get("/vouchers/ZZZZ-9999")
    assert r.status_code == 404
    ok("unknown voucher -> 404")

print(f"\nALL {PASS} offline smoke tests passed ({_TMPDIR})")
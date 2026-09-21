"""End-to-end sync test against the shared (Neon) PostgreSQL database.

Uses the fixed demo device identity (DEVICE_ID / DEVICE_CODE in .env) and the
persistent demo config created by scripts/seed_neon.py. Runs the device service
against a temp SQLite, verifies pull + push + payment reconcile, then removes
only the rows the test added (sessions, payments, extra vouchers) and restores
the redeemed voucher. The demo seed itself is kept.
"""

import os
import sys
import tempfile

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _PROJECT_ROOT)

# Read the shared database URL from the admin panel .env (backend2/.env).
_BACKEND_ENV = os.path.join(_PROJECT_ROOT, "..", "backend2", ".env")
_REMOTE_URL = None
with open(_BACKEND_ENV, "r") as f:
    for line in f:
        if line.startswith("DATABASE_URL="):
            _REMOTE_URL = line.strip().split("=", 1)[1]
if not _REMOTE_URL:
    raise SystemExit("could not read DATABASE_URL from backend2/.env")

_TMPDIR = tempfile.mkdtemp(prefix="devicesvc_sync_")
os.environ["REMOTE_DATABASE_URL"] = _REMOTE_URL
os.environ["LOCAL_DB_PATH"] = os.path.join(_TMPDIR, "device.db")
os.environ["SYNC_ON_STARTUP"] = "false"
os.environ["SYNC_INTERVAL_SECONDS"] = "0"

import sqlite3  # noqa: E402

import config as config_mod  # noqa: E402
from database import init_db, local_session, remote_session  # noqa: E402
from models.device import Device  # noqa: E402
from models.payment import Payment  # noqa: E402
from models.session import SessionModel  # noqa: E402
from models.session_device_log import SessionDeviceLog  # noqa: E402
from models.voucher import Voucher  # noqa: E402
from scripts.seed_neon import DEVICE_CODE, DEVICE_ID, seed_all  # noqa: E402
from sqlalchemy import delete, update  # noqa: E402
from sync import engine  # noqa: E402

# Device identity must be fixed before any code calls resolve_device_id().
os.environ["DEVICE_ID"] = DEVICE_ID
os.environ["DEVICE_CODE"] = DEVICE_CODE
os.environ["DEVICE_NAME"] = f"Demo {DEVICE_CODE}"
config_mod.DEVICE_ID = DEVICE_ID
config_mod.DEVICE_CODE = DEVICE_CODE
config_mod.DEVICE_NAME = f"Demo {DEVICE_CODE}"

PASS = 0
REDEEMED = "PHB-0001"
SEED: dict = {}
TRACKED: dict = {"sessions": [], "payments": []}
EXTRA_VOUCHERS: list[str] = []


def ok(label: str):
    global PASS
    PASS += 1
    print(f"  OK  {label}")


def local_count(table: str) -> int:
    conn = sqlite3.connect(os.environ["LOCAL_DB_PATH"])
    try:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    finally:
        conn.close()


def cleanup() -> None:
    """Remove only test-created rows; keep the demo seed. Safe to repeat."""
    with remote_session() as r:
        if TRACKED["payments"]:
            r.execute(
                delete(Payment.__table__).where(
                    Payment.__table__.c.id.in_(TRACKED["payments"])
                )
            )
        if TRACKED["sessions"]:
            r.execute(
                delete(SessionDeviceLog.__table__).where(
                    SessionDeviceLog.__table__.c.session_id.in_(TRACKED["sessions"])
                )
            )
            r.execute(
                delete(SessionModel.__table__).where(
                    SessionModel.__table__.c.id.in_(TRACKED["sessions"])
                )
            )
        if EXTRA_VOUCHERS:
            r.execute(
                delete(Voucher.__table__).where(
                    Voucher.__table__.c.code.in_(EXTRA_VOUCHERS)
                )
            )
        r.execute(
            update(Voucher.__table__)
            .where(Voucher.__table__.c.code == REDEEMED)
            .values(status="available", session_id=None, device_id=None, used_at=None)
        )
        r.commit()


def main() -> None:
    cleanup()
    global SEED
    SEED = seed_all()
    print(f"  seed ready: device {SEED['device_code']} campaign={SEED['campaign_name']}")

    init_db()
    result = engine.run_once()
    assert result["ok"], result
    print("  sync pull:", result)
    ok("server -> device pull succeeded")

    assert local_count("campaigns") == 1
    assert local_count("booths") == 1
    assert local_count("devices") == 1
    assert local_count("device_assignments") == 1
    assert local_count("vouchers") >= SEED["voucher_count"]
    ok("config pulled into SQLite (campaigns/booths/devices/vouchers)")

    conn = sqlite3.connect(os.environ["LOCAL_DB_PATH"])
    row = conn.execute(
        "SELECT c.name FROM device_assignments a "
        "JOIN booths b ON b.id = a.booth_id "
        "JOIN campaigns c ON c.id = b.campaign_id "
        "WHERE a.device_id = ?",
        (DEVICE_ID,),
    ).fetchone()
    conn.close()
    assert row and row[0] == SEED["campaign_name"], row
    ok("device assignment -> booth -> campaign resolves locally")

    with local_session() as db:
        dv = db.get(Device, DEVICE_ID)
        assert dv and dv.camera_profile_id == SEED["camera"], dv.camera_profile_id
        assert dv and dv.printer_profile_id == SEED["printer"]
        ok("device camera/printer profiles synced down")

    # ---- live device API usage, then push -------------------------------
    from fastapi.testclient import TestClient

    from main import app

    with TestClient(app) as client:
        r = client.get("/config")
        assert r.status_code == 200
        cfg = r.json()
        assert cfg["campaign"]["name"] == SEED["campaign_name"]
        assert cfg["booth"]["name"] == SEED["booth_name"]
        assert len(cfg["frames"]) == 1
        assert cfg["offline_vouchers"] >= SEED["voucher_count"]
        assert cfg["camera_profile"]["resolution"] == SEED["camera_resolution"]
        ok("GET /config returns synced config")

        r = client.get("/templates")
        assert r.status_code == 200, r.text
        templates = r.json()
        assert [t["id"] for t in templates] == [SEED["frame_public"]]
        assert templates[0]["publish_state"] == "public"
        ok("GET /templates lists campaign frame templates")

        r = client.post(
            "/sessions",
            json={
                "frame_template_id": SEED["frame_public"],
            },
        )
        assert r.status_code == 201, r.text
        session_id = r.json()["id"]
        assert r.json()["state"] == "started"
        assert r.json()["device_code"] == DEVICE_CODE
        assert r.json()["frame_template_id"] == SEED["frame_public"]
        assert r.json()["frame_template_name"] == SEED["frame_name"]
        ok("created session via device API (with frame)")

        # frame can only change until it is locked; bogus frame is rejected
        r = client.patch(
            f"/sessions/{session_id}", json={"frame_template_id": "bogus"}
        )
        assert r.status_code == 400, r.text
        ok("invalid frame rejected while frame settable (400)")

        r = client.patch(f"/sessions/{session_id}", json={"state": "simulation"})
        assert r.status_code == 200 and r.json()["state"] == "simulation", r.text
        ok("PATCH /sessions/{id} state -> simulation")

        # frame is locked after simulation: later steps ignore a different frame
        r = client.patch(f"/sessions/{session_id}/simulation")
        assert r.status_code == 200, r.text
        assert r.json()["frame_template_id"] == SEED["frame_public"]
        assert r.json()["state"] == "take_photo"
        ok("frame locked after simulation (later steps ignore frame)")

        r = client.patch(f"/sessions/{session_id}/print")
        assert r.status_code == 200 and r.json()["state"] == "print", r.text
        r = client.patch(f"/sessions/{session_id}", json={"state": "complete"})
        assert r.status_code == 200 and r.json()["state"] == "complete", r.text
        ok("lifecycle /simulation /print + state -> complete")

        # completed session cannot continue lifecycle -> 409
        r = client.patch(f"/sessions/{session_id}/simulation")
        assert r.status_code == 409, r.text
        ok("invalid transition on completed session (409)")

        r = client.post(
            "/payments",
            json={
                "session_id": session_id,
                "campaign_id": SEED["campaign"],
                "booth_id": SEED["booth"],
                "device_id": DEVICE_ID,
                "amount": 45000,
                "method": "QRIS",
            },
        )
        assert r.status_code == 201, r.text
        payment_id = r.json()["payment"]["id"]
        ok("created payment via device API")

        r = client.post(
            f"/vouchers/{REDEEMED}/redeem",
            json={"session_id": session_id},
        )
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "available"
        ok("verified offline voucher via device API (no consume)")

        TRACKED["sessions"].append(session_id)
        TRACKED["payments"].append(payment_id)

    res = engine.run_once()
    assert res["ok"], res
    assert res["pending"] == 0, res
    print("  sync push:", res["ok"], "pending:", res["pending"])
    ok("device -> server push succeeded")

    with remote_session() as r:
        sess = r.get(SessionModel, session_id)
        assert sess is not None
        assert sess.state == "complete"
        assert sess.frame_template_id == SEED["frame_public"]
        ok("session pushed to server (complete + frame)")

        logs = (
            r.query(SessionDeviceLog)
            .filter(SessionDeviceLog.session_id == session_id)
            .order_by(SessionDeviceLog.created_at)
            .all()
        )
        assert logs and logs[-1].frame_template_id == SEED["frame_public"]
        assert logs[-1].frame_template_name == SEED["frame_name"]
        ok("server session device log has frame snapshot")

        pay = r.get(Payment, payment_id)
        assert pay is not None
        assert pay.provider_ref == f"stub-{payment_id}"
        assert pay.status == "pending"
        ok("payment pushed to server (provider_ref intact)")

        v = r.query(Voucher).filter(Voucher.code == REDEEMED).first()
        assert v.status == "available" and v.session_id is None
        ok("voucher verify did not consume/push voucher")

    # Simulate the admin adding a voucher while the device was "offline".
    with remote_session() as r:
        from scripts.seed_neon import sid

        r.add(
            Voucher(
                id=sid("voucher/PHB-9999"),
                batch_id=SEED["batch"],
                code="PHB-9999",
                status="available",
            )
        )
        r.commit()
    EXTRA_VOUCHERS.append("PHB-9999")

    res = engine.run_once()
    assert res["ok"], res
    assert local_count("vouchers") >= SEED["voucher_count"] + 1
    conn = sqlite3.connect(os.environ["LOCAL_DB_PATH"])
    has_new = conn.execute(
        "SELECT COUNT(*) FROM vouchers WHERE code='PHB-9999'"
    ).fetchone()[0]
    conn.close()
    assert has_new == 1
    ok("new server voucher pulled down")

    # Pull must keep the locally-verified voucher as 'available'.
    with local_session() as db:
        used = db.query(Voucher).filter(Voucher.code == REDEEMED).first()
        assert used.status == "available" and used.session_id is None
    ok("locally-verified voucher preserved across pull")

    # Payment status reconcile: flip a pushed payment to succeeded on the server
    # (as a webhook would), then pull and confirm the device sees it.
    with remote_session() as r:
        pay = r.get(Payment, payment_id)
        pay.status = "succeeded"
        r.commit()
    res = engine.run_once()
    assert res["ok"], res
    with local_session() as db:
        pay_local = db.get(Payment, payment_id)
        assert pay_local.status == "succeeded"
    ok("payment status webhook change pulled down")

    # INSERT-only push must NOT clobber the newer server status back to pending.
    res = engine.run_once()
    assert res["ok"], res
    with remote_session() as r:
        pay = r.get(Payment, payment_id)
        assert pay.status == "succeeded"
    ok("payment push does not clobber server status")

    print(f"\nALL {PASS} sync integration tests passed")
    cleanup()
    print("test data cleaned up from Neon (demo seed kept)")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        cleanup()
        raise
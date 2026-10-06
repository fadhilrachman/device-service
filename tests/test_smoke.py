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
from models.device_sync_log import DeviceSyncLog  # noqa: E402
from models.session import SessionModel  # noqa: E402
from models.frame_template import FrameTemplate, PublishState  # noqa: E402
from models.voucher import Voucher  # noqa: E402
from models.voucher_batch import VoucherBatch  # noqa: E402

import base64  # noqa: E402
import json  # noqa: E402
import time  # noqa: E402


def _make_token(
    user_id: str = "test-device-1",
    device_id: str = "test-device-1",
    client_id: str | None = "TEST-DEV-0001",
) -> str:
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
    if client_id is not None:
        payload["client_id"] = client_id
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

    # token without client_id claim -> 401 (identity comes from the token)
    r = client.get(
        "/devices/me",
        headers={"Authorization": f"Bearer {_make_token_no_device()}"},
    )
    assert r.status_code == 401 and "client_id" in r.json()["detail"], r.text
    ok("GET /devices/me without client_id claim -> 401")

    # token client_id that is not registered -> 401
    r = client.get(
        "/devices/me",
        headers={"Authorization": f"Bearer {_make_token('ghost', 'ghost-device', 'GHOST-DEV')}"},
    )
    assert r.status_code == 401 and "Unknown device" in r.json()["detail"], r.text
    ok("GET /devices/me unregistered token client_id -> 401")

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

    # 9. Bulk sync with an optional device self-report
    r = client.post("/sync/bulk", json={})
    assert r.status_code == 400 and "Empty bulk payload" in r.json()["detail"], r.text
    ok("POST /sync/bulk empty payload -> 400")

    # device-only push (nothing to flush) is valid and writes the kiosk columns
    device_report = {
        "app_version": "1.4.0",
        "storage_state": "free 12.4GB",
        "camera_health": "connect",
        "printer_health": "disconnect",
    }
    r = client.post("/sync/bulk", json={"device": device_report, "meta": {"app_version": "1.4.0"}})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["device_updated"] is True, body
    assert all(s["ok"] == 0 and s["failed"] == 0 for s in body["summary"].values()), body
    with remote_session() as db:
        dev = db.get(Device, device_id)
        assert dev.app_version == "1.4.0", dev.app_version
        assert dev.storage_state == "free 12.4GB", dev.storage_state
        assert dev.camera_health == "connect", dev.camera_health
        assert dev.printer_health == "disconnect", dev.printer_health
        assert dev.connectivity == "online", dev.connectivity
        assert dev.last_heartbeat is not None  # still stamped in DB, hidden from API responses
        assert dev.last_synced_at is not None
        cfg_device = body["changes"]["config"]["device"]
        assert "last_heartbeat" not in cfg_device, cfg_device
        assert "last_seen_at" not in cfg_device, cfg_device
        assert cfg_device["connectivity"] == "online"
        assert cfg_device["last_synced_at"] is not None
        log = db.get(DeviceSyncLog, body["sync_log_id"])
        assert log.meta["device"]["camera_health"] == "connect", log.meta  # enum stored as plain value
        assert log.meta["app_version"] == "1.4.0", log.meta  # caller meta kept as-is
    ok("POST /sync/bulk device-only push updates the device row and logs meta.device")

    # identical payload -> row unchanged, reported as device_updated False
    r = client.post("/sync/bulk", json={"device": device_report})
    assert r.status_code == 201 and r.json()["device_updated"] is False, r.text
    ok("repeat device payload -> device_updated False")

    # heartbeat semantics: only the sent fields are overwritten
    r = client.post("/sync/bulk", json={"device": {"printer_health": "connect"}})
    assert r.status_code == 201 and r.json()["device_updated"] is True, r.text
    with remote_session() as db:
        dev = db.get(Device, device_id)
        assert dev.printer_health == "connect"
        assert dev.camera_health == "connect", dev.camera_health      # untouched
        assert dev.app_version == "1.4.0", dev.app_version      # untouched
        assert dev.storage_state == "free 12.4GB", dev.storage_state  # untouched
    ok("partial device block only overwrites the fields it sends")

    # camera/printer health is a closed vocabulary
    for bad in ["ok", "ready", "CONNECT", "unknown", ""]:
        r = client.post("/sync/bulk", json={"device": {"camera_health": bad}})
        assert r.status_code == 422, (bad, r.text)
    r = client.post("/sync/bulk", json={"device": {"printer_health": "paper_low"}})
    assert r.status_code == 422, r.text
    ok("POST /sync/bulk camera/printer_health outside connect|disconnect -> 422")

    # capabilities is not kiosk-writable
    r = client.post("/sync/bulk", json={"device": {"capabilities": {"printer": "ezprint"}}})
    assert r.status_code == 422, r.text
    with remote_session() as db:
        assert db.get(Device, device_id).capabilities is None
    ok("POST /sync/bulk device.capabilities -> 422 and column untouched")

    # identity/binding columns are server-managed -> rejected, not silently ignored
    r = client.post("/sync/bulk", json={"device": {"device_code": "HACKED"}})
    assert r.status_code == 422, r.text
    r = client.post("/sync/bulk", json={"device": {"tenant_id": "org-1"}})
    assert r.status_code == 422, r.text
    ok("POST /sync/bulk device.device_code / tenant_id -> 422")

    # column width enforced by the schema, not by a Postgres truncation error
    r = client.post("/sync/bulk", json={"device": {"app_version": "x" * 51}})
    assert r.status_code == 422, r.text
    ok("POST /sync/bulk device.app_version > 50 chars -> 422")

    # records without a device block keep working, device_updated stays null
    r = client.post(
        "/sync/bulk",
        json={"sessions": [{"session_local_id": "ses_smoke_bulk_1", "state": "complete", "offline": True}]},
    )
    assert r.status_code == 201, r.text
    assert r.json()["device_updated"] is None, r.text
    assert r.json()["summary"]["session"]["ok"] == 1, r.text
    with remote_session() as db:
        synced = (
            db.query(SessionModel).filter(SessionModel.client_ref == "ses_smoke_bulk_1").first()
        )
        assert synced is not None and synced.code is not None, r.text
        assert synced.code.startswith("SES-"), synced.code
    ok("POST /sync/bulk records only -> device_updated null")

    # 10. Pull side of POST /sync/bulk: vouchers since the watermark, config, frames
    with remote_session() as db:
        db.get(Device, device_id).last_synced_at = None  # a device that never synced
        for log in db.query(DeviceSyncLog).filter(DeviceSyncLog.device_id == device_id).all():
            log.meta = None  # ...and one that was never handed any frames
        db.commit()

    r = client.post("/sync/bulk", json={"device": {"app_version": "1.4.0"}})
    assert r.status_code == 201, r.text
    changes = r.json()["changes"]
    assert changes["voucher_since"] is None, changes["voucher_since"]
    assert sorted(v["code"] for v in changes["vouchers"]) == [
        "MINE-0001",
        "MINE-LEGACY",
        "MINE-USED",
    ], changes["vouchers"]
    assert all(v["updated_at"] for v in changes["vouchers"])
    with remote_session() as db:
        assert db.get(Device, device_id).last_synced_at is not None
    ok("first sync returns every device voucher and stamps devices.last_synced_at")

    cfg = changes["config"]
    assert set(cfg) == {
        "device",
        "camera_profile",
        "printer_profile",
        "offline_vouchers",
    }, set(cfg)
    assert "frames" not in cfg, cfg
    assert not {"storage_state", "camera_health", "printer_health"} & set(cfg["device"]), sorted(cfg["device"])
    live = client.get("/config").json()
    assert {"storage_state", "camera_health", "printer_health"} <= set(live["device"])
    for key in ("camera_profile", "printer_profile", "offline_vouchers"):
        assert cfg[key] == live[key], key
    ok("changes.config mirrors GET /config minus the three health fields and frames")

    ft = changes["frame_templates"]
    assert ft["campaign_id"] == "camp-smoke", ft["campaign_id"]
    assert [f["id"] for f in ft["campaign_frames"]] == [f["id"] for f in live["frames"]]
    assert [f["id"] for f in ft["new_frames"]] == [f["id"] for f in live["frames"]]
    ok("changes.frame_templates: campaign set, everything counts as new on first sync")

    # nothing touched since the watermark -> no vouchers, no new frames
    r = client.post("/sync/bulk", json={"device": {"app_version": "1.4.1"}})
    changes = r.json()["changes"]
    assert changes["voucher_since"] is not None
    assert changes["vouchers"] == [], changes["vouchers"]
    assert changes["frame_templates"]["new_frames"] == []
    assert [f["id"] for f in changes["frame_templates"]["campaign_frames"]] == ["frame-public-1"]
    ok("repeat sync returns no changed vouchers and no new frames")

    # a voucher created after the watermark comes back, and only it
    with remote_session() as db:
        batch = (
            db.query(VoucherBatch)
            .filter(VoucherBatch.campaign_id == "camp-smoke", VoucherBatch.name == "Smoke Batch")
            .first()
        )
        db.add(Voucher(batch_id=batch.id, code="SYNC-NEW-1", device_id=device_id))
        db.commit()
    changes = client.post("/sync/bulk", json={"device": {"app_version": "1.4.2"}}).json()["changes"]
    assert [v["code"] for v in changes["vouchers"]] == ["SYNC-NEW-1"], changes["vouchers"]
    ok("only vouchers created after last_synced_at come back")

    # a frame linked to the campaign after the last delivery shows up as new
    with remote_session() as db:
        db.add(FrameTemplate(
            id="frame-public-3",
            name="Newly Linked Frame",
            version="1",
            assets="",
            aspect="4:5",
            dimensions="",
            safe_area="",
            transforms={},
            preview_variant="1 foto",
            print_variant="",
            digital_variant="",
            checksum="newly-linked-checksum",
            compatibility="",
            publish_state=PublishState.PUBLIC,
        ))
        db.commit()
        campaign = db.get(Campaign, "camp-smoke")
        campaign.frame_templates.append(db.get(FrameTemplate, "frame-public-3"))
        db.commit()
        assert len(campaign.frame_templates) >= 1
    changes = client.post("/sync/bulk", json={"device": {"app_version": "1.4.3"}}).json()["changes"]
    ft = changes["frame_templates"]
    assert [f["id"] for f in ft["new_frames"]] == ["frame-public-3"], [f["id"] for f in ft["new_frames"]]
    assert {f["id"] for f in ft["campaign_frames"]} == {"frame-public-1", "frame-public-3"}
    ok("newly assigned frame appears in new_frames, full campaign set is always returned")

    # 11. Device authorization API (/auth/device/*) proxies to SSO
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

    # 11b. Successful token issuance flips connectivity to connect.
    import api.auth_device as auth_device_api

    class _FakeTokenResponse:
        def __init__(self, status_code, body):
            self.status_code = status_code
            self._body = body

        def json(self):
            return self._body

    class _FakeTokenSSOClient:
        def __init__(self, *args, **kwargs):
            pass

        def token(self, payload):
            assert payload["device_code"] == "sso-code-conn-1", payload
            return _FakeTokenResponse(
                200,
                {"access_token": "tok", "refresh_token": "ref",
                 "token_type": "Bearer", "expires_in": 300},
            )

    with remote_session() as db:
        db.add(
            Device(
                id="test-device-conn",
                device_code="TEST-DEV-CONN",
                device_code_sso="sso-code-conn-1",
                status="active",
                connectivity="disconnect",
            )
        )
        db.commit()
    _real_sso_client = auth_device_api.SSOClient
    auth_device_api.SSOClient = _FakeTokenSSOClient
    try:
        r = client.post(
            "/auth/device/token/",
            json={
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                "device_code": "sso-code-conn-1",
            },
        )
        assert r.status_code == 200, r.text
        assert r.json()["access_token"] == "tok", r.text
    finally:
        auth_device_api.SSOClient = _real_sso_client
    with remote_session() as db:
        row = db.get(Device, "test-device-conn")
        assert row.connectivity == "connect", row.connectivity
        assert row.is_verified is True, row.is_verified
    ok("POST /auth/device/token/ success flips connectivity to connect + verified")

    # 12. WhatsApp send (WAHA free text + image), WAHA itself is faked out
    import config as svc_config
    from api.whatsapp import get_whatsapp_client
    from lib.waha import WahaClient, WahaError, to_chat_id
    from lib.whatsapp import normalize_recipient

    sent = {}

    class FakeWahaClient:
        session = "default"

        def __init__(self, error=None):
            self.error = error

        def send_text(self, to, text):
            if self.error is not None:
                raise self.error
            sent.clear()
            sent.update({"kind": "text", "to": to, "text": text})
            return {"sid": "WA_FAKE", "status": "sent", "to": to, "from": self.session}

        def send_image(self, to, image_url, caption=None):
            if self.error is not None:
                raise self.error
            sent.clear()
            sent.update({"kind": "image", "to": to, "image_url": image_url, "caption": caption})
            return {"sid": "WA_FAKE_IMG", "status": "sent", "to": to, "from": self.session}

    svc_config.WAHA_BASE_URL = "https://waha.test"
    svc_config.WAHA_API_KEY = "key-test"
    app.dependency_overrides[get_whatsapp_client] = lambda: FakeWahaClient()

    r = client.post(
        "/whatsapp/send",
        json={"to": "+62 881-0220 77883", "text": "Your photo is ready!"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["message_sid"] == "WA_FAKE" and body["status"] == "sent", body
    assert body["to"] == "whatsapp:+62881022077883", body
    assert body["from_number"] == "default", body
    assert body["device_id"] == device_id, body
    assert sent == {
        "kind": "text",
        "to": "whatsapp:+62881022077883",
        "text": "Your photo is ready!",
    }, sent
    ok("POST /whatsapp/send normalizes the number and returns the WAHA id")

    r = client.post(
        "/whatsapp/send",
        json={
            "to": "whatsapp:+62881022077883",
            "text": "Here it is",
            "image_url": "https://x/y.jpg",
        },
    )
    assert r.status_code == 201 and r.json()["message_sid"] == "WA_FAKE_IMG", r.text
    assert sent["kind"] == "image" and sent["image_url"] == "https://x/y.jpg", sent
    ok("POST /whatsapp/send with image_url sends an image with caption")

    for bad in ["0811", "not-a-number", "whatsapp:+1234", "+62abc", ""]:
        r = client.post("/whatsapp/send", json={"to": bad, "text": "hi"})
        assert r.status_code in (400, 422), (bad, r.status_code, r.text)
    r = client.post("/whatsapp/send", json={"to": "+62881022077883"})
    assert r.status_code == 422, r.text
    ok("POST /whatsapp/send rejects invalid numbers and missing text")

    app.dependency_overrides[get_whatsapp_client] = lambda: FakeWahaClient(
        WahaError("waha unreachable", status_code=503)
    )
    r = client.post("/whatsapp/send", json={"to": "+62881022077883", "text": "hi"})
    assert r.status_code == 502 and "waha unreachable" in r.json()["detail"], r.text
    app.dependency_overrides[get_whatsapp_client] = lambda: FakeWahaClient(
        WahaError("chat not found", status_code=400)
    )
    r = client.post("/whatsapp/send", json={"to": "+62881022077883", "text": "hi"})
    assert r.status_code == 400 and "chat not found" in r.json()["detail"], r.text
    ok("WAHA failures map to 502 (upstream 5xx) and 400 (upstream 4xx)")

    svc_config.WAHA_BASE_URL = ""
    svc_config.WAHA_API_KEY = ""
    r = client.post("/whatsapp/send", json={"to": "+62881022077883", "text": "hi"})
    assert r.status_code == 503, r.text
    svc_config.WAHA_BASE_URL = "https://waha.test"
    svc_config.WAHA_API_KEY = "key-test"
    ok("POST /whatsapp/send without credentials -> 503")

    app.dependency_overrides.pop(get_whatsapp_client)
    r = client.post(
        "/whatsapp/send",
        json={"to": "+62881022077883", "text": "hi"},
        headers={"Authorization": f"Bearer {_make_token_no_device()}"},
    )
    assert r.status_code == 401, r.text
    ok("POST /whatsapp/send without client_id claim -> 401 (kiosk-only)")

    # client wiring reads env config and never touches the network on build
    waha_client = WahaClient()
    assert waha_client.session == "default"
    assert to_chat_id("whatsapp:+62881022077883") == "62881022077883@c.us"
    assert normalize_recipient("whatsapp:+62881022077883") == "whatsapp:+62881022077883"
    assert normalize_recipient("+62 881-0220 77883") == "whatsapp:+62881022077883"
    assert "/whatsapp/send" in app.openapi()["paths"]
    ok("WahaClient wires from config; chat id conversion accepts +62/spacing")

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

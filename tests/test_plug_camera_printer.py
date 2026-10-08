"""Tests for POST /plug/camera_and_printer (two-object body with name).

REMOTE_DATABASE_URL points at a temp SQLite file so the suite runs without
network. The device identity comes from the Bearer token claim.
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_TMPDIR = tempfile.mkdtemp(prefix="devicesvc_plug_")
os.environ["REMOTE_DATABASE_URL"] = f"sqlite:///{os.path.join(_TMPDIR, 'device.db')}"
os.environ["PAYMENT_PROVIDER"] = "stub"
os.environ["SSO_BASE_URL"] = "http://127.0.0.1:1"

from fastapi.testclient import TestClient  # noqa: E402

from database import remote_session  # noqa: E402
from main import app  # noqa: E402
from models.camera_profile import CameraProfile  # noqa: E402
from models.device import Device  # noqa: E402
from models.printer_profile import PrinterProfile  # noqa: E402

import base64  # noqa: E402
import json  # noqa: E402
import time  # noqa: E402


def _make_token(
    user_id: str = "test-device-1",
    device_id: str = "test-device-1",
    client_id: str | None = "TEST-PLUG-0001",
) -> str:
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


AUTH_HEADERS = {"Authorization": f"Bearer {_make_token()}"}

PASS = 0


def ok(label: str):
    global PASS
    PASS += 1
    print(f"  OK  {label}")


CAMERA_BODY = {
    "name": "Canon EOS 80D",
    "source": "dslr-python",
    "captured_at": "2026-10-08T12:14:08.542968+00:00",
    "adapter": {
        "type": "DSLR_TETHER",
        "vendor": "Canon.Inc",
        "model": "Canon EOS 80D",
        "allowlist": ["canon", "dslr", "eos"],
        "preferred_device": {
            "identifier": "usb:003,006",
            "label": "Canon EOS 80D",
            "usb_id": "04a9:3294",
        },
    },
    "capture_settings": {
        "resolution": {"width": 6000, "height": 3368, "source": "last_capture"},
        "aspect_ratio": "16:9",
        "orientation": "landscape",
        "mirror_preview": False,
        "exposure": {"mode": "P", "compensation": "0"},
        "iso": "Auto",
        "shutter_speed": "auto",
        "aperture": "implicit auto",
        "white_balance": "Auto",
        "focus_mode": "One Shot",
        "flash": {"supported": False, "trigger": "software"},
        "warmup_ms": 3000,
        "capture_timeout_ms": 90000,
    },
    "video_settings": {
        "pre_roll_ms": 0,
        "post_roll_ms": 0,
        "target_duration_s": None,
        "fps": 30,
        "codec": "h264",
        "bitrate_kbps": None,
        "audio_enabled": False,
        "fallback_behavior": "still_photo",
    },
}


with TestClient(app, headers=AUTH_HEADERS) as client:
    with remote_session() as db:
        db.add(
            Device(
                id="test-device-1",
                device_code="TEST-PLUG-0001",
                name="Plug Device",
                status="active",
            )
        )
        db.commit()

    # 1. Full camera object + name-only printer -> 201 with nested response
    r = client.post(
        "/plug/camera_and_printer",
        json={"camera_profile": CAMERA_BODY, "printer_profile": {"name": "PHB-58"}},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["camera_profile"]["name"] == "Canon EOS 80D", body
    assert body["camera_profile"]["source"] == "dslr-python", body
    assert body["camera_profile"]["adapter"]["model"] == "Canon EOS 80D", body
    assert body["camera_profile"]["capture_settings"]["resolution"]["width"] == 6000, body
    assert body["camera_profile"]["video_settings"]["fps"] == 30, body
    assert "captured_at" not in body["camera_profile"], body
    assert body["printer_profile"]["name"] == "PHB-58", body
    camera_id = body["camera_profile"]["id"]
    printer_id = body["printer_profile"]["id"]
    with remote_session() as db:
        dev = db.get(Device, "test-device-1")
        assert dev.camera_profile_id == camera_id, dev.camera_profile_id
        assert dev.printer_profile_id == printer_id, dev.printer_profile_id
        cam = db.get(CameraProfile, camera_id)
        assert cam.adapter["vendor"] == "Canon.Inc", cam.adapter
        assert cam.capture_settings["aspect_ratio"] == "16:9", cam.capture_settings
    ok("POST /plug/camera_and_printer full camera + name-only printer -> 201 nested")

    # 2. Re-plug updates the linked profiles instead of creating new rows
    with remote_session() as db:
        n_cam_before = db.query(CameraProfile).count()
        n_prn_before = db.query(PrinterProfile).count()
    r = client.post(
        "/plug/camera_and_printer",
        json={
            "camera_profile": {**CAMERA_BODY, "source": "dslr-python-2"},
            "printer_profile": {"name": "PHB-58b"},
        },
    )
    assert r.status_code == 201, r.text
    assert r.json()["camera_profile"]["id"] == camera_id, r.text
    assert r.json()["camera_profile"]["source"] == "dslr-python-2", r.text
    assert r.json()["printer_profile"]["id"] == printer_id, r.text
    assert r.json()["printer_profile"]["name"] == "PHB-58b", r.text
    with remote_session() as db:
        assert db.query(CameraProfile).count() == n_cam_before
        assert db.query(PrinterProfile).count() == n_prn_before
    ok("re-plug updates linked profiles (same ids, no new rows)")

    # 3. Camera only / printer only are accepted
    r = client.post("/plug/camera_and_printer", json={"camera_profile": CAMERA_BODY})
    assert r.status_code == 201 and r.json()["camera_profile"] is not None, r.text
    ok("camera-only plug -> 201")
    r = client.post("/plug/camera_and_printer", json={"printer_profile": {"name": "PHB-X"}})
    assert r.status_code == 201 and r.json()["printer_profile"]["name"] == "PHB-X", r.text
    ok("printer-only plug -> 201")

    # 4. Empty body and blank names are rejected
    r = client.post("/plug/camera_and_printer", json={})
    assert r.status_code == 400, r.text
    r = client.post("/plug/camera_and_printer", json={"camera_profile": {"name": "  "}})
    assert r.status_code == 400, r.text
    r = client.post("/plug/camera_and_printer", json={"printer_profile": {}})
    assert r.status_code == 422, r.text
    ok("empty/blank/missing-name bodies -> 400/422")

print(f"\nALL {PASS} plug tests passed ({_TMPDIR})")

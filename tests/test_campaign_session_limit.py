"""Tests for GET /campaigns/{id}/session-limit (used quota from completed sessions)."""

import base64
import json
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_TMPDIR = tempfile.mkdtemp(prefix="devicesvc_camplimit_")
os.environ["REMOTE_DATABASE_URL"] = f"sqlite:///{os.path.join(_TMPDIR, 'device.db')}"
os.environ["PAYMENT_PROVIDER"] = "stub"
os.environ["SSO_BASE_URL"] = "http://127.0.0.1:1"

from fastapi.testclient import TestClient  # noqa: E402

from database import init_db, remote_session  # noqa: E402
from main import app  # noqa: E402
from models.campaign import Campaign  # noqa: E402
from models.device import Device  # noqa: E402
from models.session import SessionModel, SessionState  # noqa: E402


def _make_token() -> str:
    def _b64(data: dict) -> str:
        raw = json.dumps(data).encode("utf-8")
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")

    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "user_id": "test-device-1",
        "device_id": "dev-limit-1",
        "client_id": "TEST-LIMIT-01",
        "iat": 0,
        "exp": int(time.time()) + 3600,
    }
    return f"{_b64(header)}.{_b64(payload)}.sig"


AUTH_HEADERS = {"Authorization": f"Bearer {_make_token()}"}

PASS = 0


def ok(msg: str) -> None:
    global PASS
    PASS += 1
    print("  OK ", msg)


init_db()

db = remote_session()
camp = Campaign(name="Limit Campaign", session_limit=5)
db.add(camp)
db.flush()
nolimit = Campaign(name="No Limit Campaign")
db.add(nolimit)
db.flush()
device = Device(device_code="TEST-LIMIT-01", name="Limit Device")
db.add(device)
db.flush()
for i in range(3):
    db.add(SessionModel(campaign_id=camp.id, device_id=device.id, state=SessionState.COMPLETE))
db.add(SessionModel(campaign_id=camp.id, device_id=device.id, state=SessionState.STARTED))
gone = SessionModel(campaign_id=camp.id, device_id=device.id, state=SessionState.COMPLETE)
db.add(gone)
db.flush()
from lib.time import wib_now  # noqa: E402

gone.deleted_at = wib_now()
db.add(SessionModel(campaign_id=nolimit.id, device_id=device.id, state=SessionState.COMPLETE))
db.commit()
camp_id, nolimit_id = camp.id, nolimit.id
db.close()

client = TestClient(app)

r = client.get(f"/campaigns/{camp_id}/session-limit", headers=AUTH_HEADERS)
assert r.status_code == 200, r.text
body = r.json()
assert body["campaign_id"] == camp_id, body
assert body["session_limit"] == 5, body
assert body["used"] == 3, body
assert body["remaining"] == 2, body
ok("limited campaign counts completed only (started + deleted excluded)")

r = client.get(f"/campaigns/{nolimit_id}/session-limit", headers=AUTH_HEADERS)
assert r.status_code == 200, r.text
body = r.json()
assert body["session_limit"] is None and body["remaining"] is None, body
assert body["used"] == 1, body
ok("unlimited campaign returns null remaining")

r = client.get("/campaigns/does-not-exist/session-limit", headers=AUTH_HEADERS)
assert r.status_code == 404, r.text
ok("unknown campaign -> 404")

r = client.get(f"/campaigns/{camp_id}/session-limit")
assert r.status_code == 401, r.text
ok("missing token -> 401")

r = client.get("/openapi.json")
assert r.status_code == 200, r.text
assert "/campaigns/{campaign_id}/session-limit" in r.json()["paths"], r.text
ok("endpoint visible in OpenAPI schema")

print(f"\nALL {PASS} campaign session-limit tests passed ({_TMPDIR})")

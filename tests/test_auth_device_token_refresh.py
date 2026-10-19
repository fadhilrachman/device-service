"""Tests for POST /auth/device/token/ and /auth/device/refresh/ last_synced_at
bookkeeping.

On an SSO 2xx both endpoints stamp devices.last_synced_at; /token/ also flips
connectivity + is_verified (via _mark_connected) and /refresh/ also sets
connectivity='connect' (via _reconnect_after_refresh, resolving the device from
the new access token's client_id claim). Non-2xx SSO responses never write.

REMOTE_DATABASE_URL points at a temp SQLite file so the suite runs without
network. The SSO client is faked per-case; no real SSO is ever touched.
"""

import base64
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_TMPDIR = tempfile.mkdtemp(prefix="devicesvc_tokref_")
os.environ["REMOTE_DATABASE_URL"] = f"sqlite:///{os.path.join(_TMPDIR, 'device.db')}"
os.environ["PAYMENT_PROVIDER"] = "stub"
os.environ["SSO_BASE_URL"] = "http://127.0.0.1:1"

from fastapi.testclient import TestClient  # noqa: E402

import api.auth_device as auth_device_api  # noqa: E402
from database import remote_session  # noqa: E402
from main import app  # noqa: E402
from models.device import Device  # noqa: E402

PASS = 0


def ok(label: str):
    global PASS
    PASS += 1
    print(f"  OK  {label}")


class _FakeResponse:
    def __init__(self, status_code, body):
        self.status_code = status_code
        self._body = body
        self.text = "" if body is None else str(body)

    def json(self):
        if isinstance(self._body, Exception):
            raise self._body
        return self._body


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _fake_access_token(client_id="BE-TOK-REF-1"):
    header = _b64url(json.dumps({"alg": "RS256", "typ": "JWT"}).encode())
    payload = _b64url(json.dumps({"sub": "device-1", "client_id": client_id}).encode())
    return f"{header}.{payload}.sig-bits-not-verified-here"


def _token_body():
    return {
        "access_token": _fake_access_token(),
        "refresh_token": "new-refresh-token",
        "token_type": "Bearer",
        "expires_in": 3600,
    }


def _device(device_code="BE-TOK-REF-1", device_code_sso="sso-code-1"):
    with remote_session() as db:
        row = (
            db.query(Device)
            .filter(Device.device_code == device_code)
            .first()
        )
        if row is None:
            row = Device(
                device_code=device_code,
                name="Kiosk Test",
                device_code_sso=device_code_sso,
                password_hash=None,
            )
            db.add(row)
        db.commit()
        db.refresh(row)
        return row.id


def _row(device_code="BE-TOK-REF-1"):
    with remote_session() as db:
        row = db.query(Device).filter(Device.device_code == device_code).one()
        db.refresh(row)
        return {
            "connectivity": row.connectivity,
            "is_verified": row.is_verified,
            "last_synced_at": row.last_synced_at,
        }


with TestClient(app) as client:
    real_sso_client = auth_device_api.SSOClient
    _device()

    # 1. /token/ 200: connectivity='connect', is_verified=True, last_synced_at stamped.
    before1 = _row()
    assert before1["connectivity"] == "disconnect", before1
    assert before1["is_verified"] is False, before1
    assert before1["last_synced_at"] is None, before1

    class _TokenOkClient:
        def __init__(self, *a, **k):
            pass

        def token(self, payload):
            return _FakeResponse(200, _token_body())

    auth_device_api.SSOClient = _TokenOkClient
    try:
        r = client.post(
            "/auth/device/token/",
            json={
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                "device_code": "sso-code-1",
            },
        )
    finally:
        auth_device_api.SSOClient = real_sso_client
    assert r.status_code == 200, r.text
    assert r.json()["access_token"] == _token_body()["access_token"], r.json()
    after1 = _row()
    assert after1["connectivity"] == "connect", after1
    assert after1["is_verified"] is True, after1
    assert after1["last_synced_at"] is not None, after1
    ok("/token/ 200 stamps last_synced_at + connectivity + is_verified")

    # 2. /token/ 400 authorization_pending: no DB write, error forwarded.
    class _TokenPendingClient:
        def __init__(self, *a, **k):
            pass

        def token(self, payload):
            return _FakeResponse(400, {"error": "authorization_pending"})

    auth_device_api.SSOClient = _TokenPendingClient
    try:
        r = client.post(
            "/auth/device/token/",
            json={
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                "device_code": "sso-code-1",
            },
        )
    finally:
        auth_device_api.SSOClient = real_sso_client
    assert r.status_code == 400, r.text
    after2 = _row()
    assert after2 == after1, (after1, after2)
    ok("/token/ 400 authorization_pending writes nothing")

    # 3. /refresh/ 200: device resolved from access_token client_id claim;
    #    last_synced_at + connectivity='connect'.
    before3 = _row()
    assert before3["last_synced_at"] is not None, before3  # stamped by case 1
    class _RefreshOkClient:
        def __init__(self, *a, **k):
            pass

        def refresh(self, payload):
            return _FakeResponse(200, _token_body())

    auth_device_api.SSOClient = _RefreshOkClient
    try:
        r = client.post("/auth/device/refresh/", json={"refresh_token": "old-refresh-token"})
    finally:
        auth_device_api.SSOClient = real_sso_client
    assert r.status_code == 200, r.text
    assert r.json()["refresh_token"] == "new-refresh-token", r.json()
    after3 = _row()
    assert after3["connectivity"] == "connect", after3
    assert after3["last_synced_at"] >= before3["last_synced_at"], (before3, after3)
    ok("/refresh/ 200 stamps last_synced_at + connectivity='connect'")

    # Set back to a failed-looking state to prove case 4 writes nothing.
    with remote_session() as db:
        row = db.query(Device).filter(Device.device_code == "BE-TOK-REF-1").one()
        row.connectivity = "error"
        row.last_synced_at = None
        db.commit()

    # 4. /refresh/ 400 invalid_grant: no DB write.
    class _RefreshInvalidClient:
        def __init__(self, *a, **k):
            pass

        def refresh(self, payload):
            return _FakeResponse(400, {"error": "invalid_grant"})

    auth_device_api.SSOClient = _RefreshInvalidClient
    try:
        r = client.post("/auth/device/refresh/", json={"refresh_token": "dead-refresh-token"})
    finally:
        auth_device_api.SSOClient = real_sso_client
    assert r.status_code == 400, r.text
    after4 = _row()
    assert after4["connectivity"] == "error", after4
    assert after4["last_synced_at"] is None, after4
    ok("/refresh/ 400 invalid_grant writes nothing")

    # 5. /refresh/ 200 without/with undecodable access_token: no DB write,
    #    body still forwarded as-is.
    class _RefreshNoTokenClient:
        def __init__(self, *a, **k):
            pass

        def refresh(self, payload):
            return _FakeResponse(200, {"access_token": "", "expires_in": 3600})

    auth_device_api.SSOClient = _RefreshNoTokenClient
    try:
        r = client.post("/auth/device/refresh/", json={"refresh_token": "old-refresh-token"})
    finally:
        auth_device_api.SSOClient = real_sso_client
    assert r.status_code == 200, r.text
    assert r.json() == {"access_token": "", "expires_in": 3600}, r.json()
    after5 = _row()
    assert after5 == after4, (after4, after5)
    ok("/refresh/ 200 without usable access_token writes nothing and forwards body")

print(f"\n{PASS}/{PASS} checks passed")

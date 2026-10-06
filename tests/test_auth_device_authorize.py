"""Tests for POST /auth/device/authorize/ (all-or-nothing, backend2 concept parity).

REMOTE_DATABASE_URL points at a temp SQLite file so the suite runs without
network. The SSO client is faked per-case; no real SSO is ever touched.
"""

import os
import sys
import tempfile
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_TMPDIR = tempfile.mkdtemp(prefix="devicesvc_authz_")
os.environ["REMOTE_DATABASE_URL"] = f"sqlite:///{os.path.join(_TMPDIR, 'device.db')}"
os.environ["PAYMENT_PROVIDER"] = "stub"
os.environ["SSO_BASE_URL"] = "http://127.0.0.1:1"

from fastapi.testclient import TestClient  # noqa: E402

import api.auth_device as auth_device_api  # noqa: E402
from database import remote_session  # noqa: E402
from lib.sso import SSOError  # noqa: E402
from main import app  # noqa: E402
from models.device import Device  # noqa: E402

PASS = 0


def ok(label: str):
    global PASS
    PASS += 1
    print(f"  OK  {label}")


def _tenant() -> str:
    return str(uuid.uuid4())


def _device_count() -> int:
    with remote_session() as db:
        return db.query(Device).count()


class _FakeResponse:
    def __init__(self, status_code, body):
        self.status_code = status_code
        self._body = body
        self.text = "" if body is None else str(body)

    def json(self):
        if isinstance(self._body, Exception):
            raise self._body
        return self._body


def _grant(device_code="sso-code-1", user_code="ABCD-EFGH"):
    return {
        "device_code": device_code,
        "user_code": user_code,
        "verification_uri": "https://sso.example/verify",
        "verification_uri_complete": f"https://sso.example/verify?user_code={user_code}",
        "expires_in": 600,
        "interval": 5,
    }


with TestClient(app) as client:
    real_sso_client = auth_device_api.SSOClient

    # 1. Success: row bound + SSO body + injected client_id + rewritten URIs.
    tenant = _tenant()
    before = _device_count()

    class _SuccessClient:
        def __init__(self, *a, **k):
            pass

        def authorize(self, payload):
            assert payload["tenant_id"] == tenant, payload
            assert payload["audience"] == "photobooth-api", payload
            assert payload["scopes"] == ["commerce.orders.write", "commerce.payments.process"], payload
            assert payload["client_id"].startswith("BE-"), payload
            return _FakeResponse(200, _grant())

    auth_device_api.SSOClient = _SuccessClient
    try:
        r = client.post("/auth/device/authorize/", json={"device_name": "Kiosk 1", "tenant_id": tenant})
    finally:
        auth_device_api.SSOClient = real_sso_client
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["client_id"].startswith("BE-"), body
    assert body["device_code"] == "sso-code-1", body
    assert body["verification_uri"] == "https://account.arnatech.id/id/device/verify", body
    assert body["verification_uri_complete"].startswith("https://account.arnatech.id/id/device/verify?user_code="), body
    assert _device_count() == before + 1
    with remote_session() as db:
        row = db.query(Device).filter(Device.device_code == body["client_id"]).one()
        assert row.tenant_id == tenant, row.tenant_id
        assert row.device_code_sso == "sso-code-1", row.device_code_sso
        assert row.user_code_sso == "ABCD-EFGH", row.user_code_sso
    ok("success binds tenant + SSO codes and returns client_id with account URIs")

    # 2. SSO non-2xx (409): mapped with upstream tag, row rolled back.
    tenant2 = _tenant()
    before = _device_count()

    class _ConflictClient:
        def __init__(self, *a, **k):
            pass

        def authorize(self, payload):
            return _FakeResponse(409, {"detail": "already authorized"})

    auth_device_api.SSOClient = _ConflictClient
    try:
        r = client.post("/auth/device/authorize/", json={"device_name": "Kiosk 2", "tenant_id": tenant2})
    finally:
        auth_device_api.SSOClient = real_sso_client
    assert r.status_code == 409, (r.status_code, r.text)
    assert "SSO authorize returned 409" in r.json()["detail"], r.text
    assert _device_count() == before, "failed authorize left an orphan row"
    ok("SSO 409 maps to 409 with upstream tag and rolls back (no orphan)")

    # 3. Duplicate tenant_id: 409 before SSO is ever called.
    tenant3 = _tenant()
    with remote_session() as db:
        db.add(Device(device_code="BE-DUP-TENANT", name="Taken", tenant_id=tenant3, status="active"))
        db.commit()
    calls = []

    class _NeverCalledClient:
        def __init__(self, *a, **k):
            pass

        def authorize(self, payload):
            calls.append(payload)
            return _FakeResponse(200, _grant(device_code="sso-never"))

    auth_device_api.SSOClient = _NeverCalledClient
    try:
        r = client.post("/auth/device/authorize/", json={"device_name": "Kiosk 3", "tenant_id": tenant3})
    finally:
        auth_device_api.SSOClient = real_sso_client
    assert r.status_code == 409, (r.status_code, r.text)
    assert "tenant_id" in r.json()["detail"], r.text
    assert calls == [], "SSO must not be called when tenant is already taken"
    ok("duplicate tenant_id -> 409 naming the field, SSO untouched")

    # 4. SSO unreachable: 502, no orphan row.
    tenant4 = _tenant()
    before = _device_count()

    class _UnreachableClient:
        def __init__(self, *a, **k):
            pass

        def authorize(self, payload):
            raise SSOError("SSO service unreachable: refused")

    auth_device_api.SSOClient = _UnreachableClient
    try:
        r = client.post("/auth/device/authorize/", json={"device_name": "Kiosk 4", "tenant_id": tenant4})
    finally:
        auth_device_api.SSOClient = real_sso_client
    assert r.status_code == 502, (r.status_code, r.text)
    assert _device_count() == before, "unreachable SSO left an orphan row"
    ok("SSO unreachable -> 502 with no orphan row")

    # 5. SSO 200 without device_code: 502, no orphan row.
    tenant5 = _tenant()
    before = _device_count()

    class _NoCodeClient:
        def __init__(self, *a, **k):
            pass

        def authorize(self, payload):
            return _FakeResponse(200, {"user_code": "ABCD-EFGH"})

    auth_device_api.SSOClient = _NoCodeClient
    try:
        r = client.post("/auth/device/authorize/", json={"device_name": "Kiosk 5", "tenant_id": tenant5})
    finally:
        auth_device_api.SSOClient = real_sso_client
    assert r.status_code == 502, (r.status_code, r.text)
    assert "missing device_code" in r.json()["detail"], r.text
    assert _device_count() == before, "malformed SSO grant left an orphan row"
    ok("SSO grant without device_code -> 502 with no orphan row")

    # 6. Extra fields (scopes/audience/client_id) are rejected with 422.
    r = client.post(
        "/auth/device/authorize/",
        json={"device_name": "Kiosk 6", "tenant_id": _tenant(), "scopes": ["x"]},
    )
    assert r.status_code == 422, (r.status_code, r.text)
    r = client.post(
        "/auth/device/authorize/",
        json={"device_name": "Kiosk 6", "tenant_id": _tenant(), "audience": "other-api"},
    )
    assert r.status_code == 422, (r.status_code, r.text)
    r = client.post(
        "/auth/device/authorize/",
        json={"device_name": "Kiosk 6", "tenant_id": _tenant(), "client_id": "BE-FORGE"},
    )
    assert r.status_code == 422, (r.status_code, r.text)
    ok("scopes/audience/client_id -> 422 (server-fixed grant, same as backend2)")

print(f"\nALL {PASS} authorize tests passed ({_TMPDIR})")

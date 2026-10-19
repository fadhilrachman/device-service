"""Tests for POST /auth/resource-token (gateway to SSO /v1/devices/resource-token/).

REMOTE_DATABASE_URL points at a temp SQLite file so the suite runs without
network. The SSO client is faked per-case; no real SSO is ever touched.
"""

import base64
import json
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_TMPDIR = tempfile.mkdtemp(prefix="devicesvc_restok_")
os.environ["REMOTE_DATABASE_URL"] = f"sqlite:///{os.path.join(_TMPDIR, 'device.db')}"
os.environ["PAYMENT_PROVIDER"] = "stub"
os.environ["SSO_BASE_URL"] = "http://127.0.0.1:1"

from fastapi.testclient import TestClient  # noqa: E402

import api.auth_device as auth_device_api  # noqa: E402
from lib.sso import SSOError  # noqa: E402
from main import app  # noqa: E402


def _make_token(client_id="TEST-RES-01"):
    def _b64(data):
        return base64.urlsafe_b64encode(json.dumps(data).encode()).rstrip(b"=").decode()

    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "user_id": "test-device-1",
        "device_id": "test-device-1",
        "client_id": client_id,
        "iat": 0,
        "exp": int(time.time()) + 3600,
    }
    return f"{_b64(header)}.{_b64(payload)}.sig"


def _auth(client_id="TEST-RES-01"):
    return {"Authorization": f"Bearer {_make_token(client_id)}"}


class _FakeResponse:
    def __init__(self, status_code, body):
        self.status_code = status_code
        self._body = body
        self.text = "" if body is None else str(body)

    def json(self):
        if isinstance(self._body, Exception):
            raise self._body
        return self._body


def _client():
    return TestClient(app)


def test_missing_token_is_401():
    with _client() as client:
        r = client.post("/auth/resource-token/", json={"audience": "storage-api"})
    assert r.status_code == 401, r.text


def test_success_forwards_token_and_body():
    seen = {}

    class _SuccessClient:
        def __init__(self, *a, **k):
            pass

        def resource_token(self, payload, access_token):
            seen["payload"] = payload
            seen["access_token"] = access_token
            return _FakeResponse(
                200,
                {"access_token": "res-tok", "token_type": "Bearer", "expires_in": 300},
            )

    real = auth_device_api.SSOClient
    auth_device_api.SSOClient = _SuccessClient
    try:
        with _client() as client:
            r = client.post(
                "/auth/resource-token/",
                json={"audience": "storage-api", "scopes": ["files.write"], "custom": "x"},
                headers=_auth(),
            )
    finally:
        auth_device_api.SSOClient = real
    assert r.status_code == 200, r.text
    assert r.json()["access_token"] == "res-tok", r.text
    assert seen["access_token"] == _make_token(), seen
    assert seen["payload"]["audience"] == "storage-api", seen
    assert seen["payload"]["scopes"] == ["files.write"], seen
    assert seen["payload"]["custom"] == "x", seen


def test_upstream_error_is_forwarded():
    class _DeniedClient:
        def __init__(self, *a, **k):
            pass

        def resource_token(self, payload, access_token):
            return _FakeResponse(403, {"detail": "cannot mint for this resource"})

    real = auth_device_api.SSOClient
    auth_device_api.SSOClient = _DeniedClient
    try:
        with _client() as client:
            r = client.post("/auth/resource-token/", json={"audience": "other"}, headers=_auth())
    finally:
        auth_device_api.SSOClient = real
    assert r.status_code == 403, (r.status_code, r.text)
    assert "cannot mint" in r.json()["detail"], r.text


def test_sso_unreachable_is_502():
    class _UnreachableClient:
        def __init__(self, *a, **k):
            pass

        def resource_token(self, payload, access_token):
            raise SSOError("SSO service unreachable: refused")

    real = auth_device_api.SSOClient
    auth_device_api.SSOClient = _UnreachableClient
    try:
        with _client() as client:
            r = client.post("/auth/resource-token/", json={"audience": "storage-api"}, headers=_auth())
    finally:
        auth_device_api.SSOClient = real
    assert r.status_code == 502, (r.status_code, r.text)


def test_openapi_lists_resource_token():
    with _client() as client:
        r = client.get("/openapi.json", headers=_auth())
    assert r.status_code == 200, r.text
    assert "/auth/resource-token/" in r.json()["paths"], r.text

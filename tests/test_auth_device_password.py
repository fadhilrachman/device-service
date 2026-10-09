"""Tests for device password verification endpoint.

Identity comes from the Bearer token's client_id claim (lib.device_identity);
the body carries only ``password``.
"""

import base64
import json
import os
import sys
import tempfile
import time
from fastapi.testclient import TestClient
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_TMPDIR = tempfile.mkdtemp(prefix="devicesvc_pw_")
os.environ["REMOTE_DATABASE_URL"] = f"sqlite:///{os.path.join(_TMPDIR, 'device.db')}"
os.environ["PAYMENT_PROVIDER"] = "stub"
os.environ["SSO_BASE_URL"] = "http://127.0.0.1:1"

from database import remote_session  # noqa: E402
from lib.password import hash_password  # noqa: E402
from main import app  # noqa: E402
from models.device import Device  # noqa: E402


def _make_token(client_id="TEST-PW-01"):
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


def _auth(client_id="TEST-PW-01"):
    return {"Authorization": f"Bearer {_make_token(client_id)}"}


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        with remote_session() as db:
            db.add(
                Device(
                    id="dev-pw-test-1",
                    device_code="TEST-PW-01",
                    name="Test Password Device",
                    status="active",
                    password_hash=hash_password("123456"),
                )
            )
            db.add(
                Device(
                    id="dev-pw-test-2",
                    device_code="TEST-PW-02",
                    name="Test No Password Device",
                    status="active",
                    password_hash=None,
                )
            )
            db.commit()
        yield c


def test_valid_password(client):
    r = client.post("/auth/device/verify-password/", json={"password": "123456"}, headers=_auth())
    assert r.status_code == 200, r.text
    assert r.json()["success"] is True
    assert r.json()["message"] == "Password verified"


def test_invalid_password(client):
    r = client.post("/auth/device/verify-password/", json={"password": "wrong"}, headers=_auth())
    assert r.status_code == 401, r.text
    assert "Invalid password" in r.json()["detail"]


def test_unknown_token_client_id(client):
    r = client.post(
        "/auth/device/verify-password/", json={"password": "123456"}, headers=_auth("GHOST-DEV")
    )
    assert r.status_code == 401, r.text


def test_missing_token(client):
    with TestClient(app) as bare:
        r = bare.post("/auth/device/verify-password/", json={"password": "123456"})
    assert r.status_code == 401, r.text


def test_device_no_password(client):
    r = client.post(
        "/auth/device/verify-password/", json={"password": "123456"}, headers=_auth("TEST-PW-02")
    )
    assert r.status_code == 401, r.text
    assert "password not set" in r.json()["detail"]


def test_empty_password(client):
    r = client.post("/auth/device/verify-password/", json={"password": ""}, headers=_auth())
    assert r.status_code == 422, r.text


def test_device_code_in_body_rejected(client):
    r = client.post(
        "/auth/device/verify-password/",
        json={"device_code": "TEST-PW-01", "password": "123456"},
        headers=_auth(),
    )
    assert r.status_code == 422, r.text

"""Tests for device password verification endpoint."""

import os
import sys
import tempfile
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
    r = client.post("/auth/device/verify-password/", json={"device_code": "TEST-PW-01", "password": "123456"})
    assert r.status_code == 200, r.text
    assert r.json()["success"] is True
    assert r.json()["message"] == "Password verified"


def test_invalid_password(client):
    r = client.post("/auth/device/verify-password/", json={"device_code": "TEST-PW-01", "password": "wrong"})
    assert r.status_code == 401, r.text
    assert "Invalid password" in r.json()["detail"]


def test_nonexistent_device(client):
    r = client.post("/auth/device/verify-password/", json={"device_code": "NONEXISTENT", "password": "123456"})
    assert r.status_code == 401, r.text
    assert "Invalid device" in r.json()["detail"]


def test_device_no_password(client):
    r = client.post("/auth/device/verify-password/", json={"device_code": "TEST-PW-02", "password": "123456"})
    assert r.status_code == 401, r.text
    assert "password not set" in r.json()["detail"]


def test_empty_password(client):
    r = client.post("/auth/device/verify-password/", json={"device_code": "TEST-PW-01", "password": ""})
    assert r.status_code == 422, r.text


def test_missing_device_code(client):
    r = client.post("/auth/device/verify-password/", json={"password": "123456"})
    assert r.status_code == 422, r.text
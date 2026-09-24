"""Commerce gateway tests with mocked HTTP (no network, no Commerce account needed)."""

import base64
import json
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_TMPDIR = tempfile.mkdtemp(prefix="devicesvc_commerce_")
os.environ["REMOTE_DATABASE_URL"] = "postgresql://invalid:invalid@localhost:1/offline"
os.environ["LOCAL_DB_PATH"] = os.path.join(_TMPDIR, "device.db")
os.environ["DEVICE_CODE"] = "TEST-COMMERCE-01"
os.environ["DEVICE_NAME"] = "Test Commerce Device"
os.environ["SYNC_ON_STARTUP"] = "false"
os.environ["SSO_BASE_URL"] = "http://127.0.0.1:1"
os.environ["COMMERCE_PAYER_EMAIL"] = "kiosk@example.com"
os.environ["COMMERCE_OFFERS_JSON"] = json.dumps(
    {
        "camp-1": {
            "product": "22222222-2222-2222-2222-222222222222",
            "plan": "33333333-3333-3333-3333-333333333333",
            "price": "44444444-4444-4444-4444-444444444444",
            "description": "Test Photobooth Single",
        }
    }
)

from fastapi.testclient import TestClient  # noqa: E402

import api.payment as payment_api  # noqa: E402
import lib.payment_gateway as gateway_mod  # noqa: E402
from database import local_session  # noqa: E402
from lib.commerce import (  # noqa: E402
    CommerceClient,
    CommerceError,
    extract_checkout_url,
    extract_organization_id,
    extract_tenant_id,
    map_commerce_status,
    start_checkout,
)
from main import app  # noqa: E402
from lib.time import wib_now  # noqa: E402
from models.booth import Booth  # noqa: E402
from models.campaign import Campaign  # noqa: E402
from models.device_assignment import DeviceAssignment  # noqa: E402
from sync import engine  # noqa: E402

PASS = 0


def ok(label: str):
    global PASS
    PASS += 1
    print(f"  OK  {label}")


def _make_token(payload_extra: dict | None = None) -> str:
    def _b64(data: dict) -> str:
        raw = json.dumps(data).encode("utf-8")
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")

    header = {"alg": "HS256", "typ": "JWT"}
    payload = {"user_id": "test-device-1", "iat": 0, "exp": int(time.time()) + 3600}
    payload.update(payload_extra or {})
    return f"{_b64(header)}.{_b64(payload)}.sig"


ORG_HEADERS = {
    "Authorization": f"Bearer {_make_token({'org_id': 'org-111', 'tenant_id': 'ten-222'})}"
}

# ---- fake Commerce HTTP -------------------------------------------------
ROUTES: dict = {}


class FakeCommerceClient(CommerceClient):
    """Real client logic, but _request serves canned routes instead of network."""

    def _request(self, method, path, json_body=None, params=None):
        key = (method, path)
        if key not in ROUTES:
            raise AssertionError(f"unexpected Commerce call: {key}")
        status_code, body = ROUTES[key]
        if status_code >= 400:
            raise CommerceError(
                f"Commerce API error {status_code}: {body}",
                status_code=status_code,
                payload=body,
            )
        return body


_REAL_GATEWAY_CLIENT = gateway_mod.CommerceClient
_REAL_API_CLIENT = payment_api.CommerceClient
gateway_mod.CommerceClient = FakeCommerceClient
payment_api.CommerceClient = FakeCommerceClient


def _happy_routes(paid: bool = False, n: str = "1"):
    order_status = "paid" if paid else "pending_payment"
    order_id = f"order-{n}"
    invoice_id = f"inv-{n}"
    invoice_number = f"INV-ARNA-0000{n}"
    return {
        ("POST", "/orders/"): (201, {"id": order_id, "status": "draft"}),
        ("POST", f"/orders/{order_id}/submit/"): (
            201,
            {
                "order": {"id": order_id, "status": order_status},
                "invoice": {
                    "id": invoice_id,
                    "invoice_number": invoice_number,
                    "status": "paid" if paid else "unpaid",
                },
                "subscription": {"id": f"sub-{n}", "status": "pending"},
            },
        ),
        ("POST", f"/orders/{order_id}/create-payment/"): (
            201,
            {"invoice_url": f"https://checkout.xendit.co/web/{invoice_id}"},
        ),
        ("GET", f"/orders/{order_id}/"): (200, {"id": order_id, "status": order_status}),
        ("GET", f"/invoices/{invoice_id}/"): (
            200,
            {
                "id": invoice_id,
                "invoice_number": invoice_number,
                "status": "paid" if paid else "unpaid",
            },
        ),
        ("POST", f"/orders/{order_id}/cancel/"): (
            201,
            {"id": order_id, "status": "cancelled"},
        ),
    }


# ---- unit: helpers -------------------------------------------------------
assert extract_checkout_url({"invoice_url": "https://x/y"}) == "https://x/y"
assert extract_checkout_url({"payment": {"invoice_url": "https://x/z"}}) == "https://x/z"
assert extract_checkout_url({"checkout_url": "https://a", "invoice_url": "https://b"}) == "https://a"
assert extract_checkout_url({"nothing": 1}) is None
assert extract_checkout_url(None) is None
ok("extract_checkout_url (top-level, nested, missing)")

assert extract_organization_id({"organization_id": "o1"}) == "o1"
assert extract_organization_id({"org_id": "o2"}) == "o2"
assert extract_organization_id({}) is None
assert extract_tenant_id({"tenant_id": "t1"}) == "t1"
assert extract_tenant_id({}) is None
ok("extract_organization_id / extract_tenant_id (incl. org_id fallback)")

assert map_commerce_status({"status": "paid"}, {"status": "unpaid"}) == "succeeded"
assert map_commerce_status({"status": "pending_payment"}, {"status": "paid"}) == "succeeded"
assert map_commerce_status({"status": "cancelled"}, None) == "failed"
assert map_commerce_status({"status": "pending_payment"}, {"status": "void"}) == "failed"
assert map_commerce_status({"status": "pending_payment"}, {"status": "unpaid"}) == "pending"
assert map_commerce_status({}, None) == "pending"
ok("map_commerce_status (paid/cancelled/void/pending)")

# ---- unit: start_checkout happy path + fallbacks --------------------------
ROUTES.update(_happy_routes())
client = FakeCommerceClient("tok", "https://product.arnatech.id/api/v1")
result = start_checkout(
    client,
    organization_id="org-111",
    tenant_id="ten-222",
    offer={
        "product": "p",
        "plan": "pl",
        "price": "pr",
        "description": "d",
    },
    payer_email="kiosk@example.com",
    description="d",
    success_url="https://s",
    failure_url="https://f",
)
assert result["order_id"] == "order-1", result
assert result["invoice_number"] == "INV-ARNA-00001", result
assert result["checkout_url"] == "https://checkout.xendit.co/web/inv-1", result
assert result["subscription_id"] == "sub-1", result
ok("start_checkout happy path (orders -> submit -> create-payment)")

# submit returning a bare Order (no invoice envelope) -> invoice found via list
ROUTES.update(
    {
        ("POST", "/orders/order-1/submit/"): (201, {"id": "order-1", "status": "pending_payment"}),
        ("GET", "/invoices/"): (
            200,
            {
                "results": [
                    {"id": "inv-9", "order": "other", "invoice_number": "INV-X"},
                    {
                        "id": "inv-1",
                        "order": "order-1",
                        "invoice_number": "INV-ARNA-00001",
                    },
                ]
            },
        ),
    }
)
result = start_checkout(
    client,
    organization_id="org-111",
    tenant_id=None,
    offer={"product": "p", "plan": "pl", "price": "pr"},
    payer_email="kiosk@example.com",
    description="d",
    success_url="https://s",
    failure_url="https://f",
)
assert result["invoice_number"] == "INV-ARNA-00001", result
ok("start_checkout falls back to invoice list when submit returns bare Order")

# missing checkout URL -> CommerceError
ROUTES.update({("POST", "/orders/order-1/create-payment/"): (201, {"ok": True})})
try:
    start_checkout(
        client,
        organization_id="org-111",
        tenant_id=None,
        offer={"product": "p", "plan": "pl", "price": "pr"},
        payer_email="kiosk@example.com",
        description="d",
        success_url="https://s",
        failure_url="https://f",
    )
    raise AssertionError("expected CommerceError")
except CommerceError as exc:
    assert "Checkout URL" in str(exc)
ok("start_checkout raises when checkout URL is missing")

# ---- api: commerce provider ----------------------------------------------
os.environ["PAYMENT_PROVIDER"] = "commerce"
_real_is_online = engine.is_online
engine.is_online = lambda force=False: True  # simulate online kiosk

with TestClient(app, headers=ORG_HEADERS) as tclient:
    r = tclient.get("/devices/me")
    assert r.status_code == 200
    device_id = r.json()["id"]

    with local_session() as db:
        db.add(Campaign(id="camp-1", name="Test Campaign", price=50000))
        db.add(
            Booth(
                id="booth-1",
                name="Booth Commerce 01",
                status="active",
                campaign_id="camp-1",
            )
        )
        db.add(
            DeviceAssignment(
                booth_id="booth-1",
                device_id=device_id,
                status="active",
                assigned_from=wib_now(),
            )
        )
        db.commit()

    ROUTES.clear()
    ROUTES.update(_happy_routes())

    # create -> 3 Commerce calls, local row persisted with commerce data
    r = tclient.post(
        "/payments",
        json={"device_id": device_id, "campaign_id": "camp-1", "method": "QRIS"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    payment = body["payment"]
    assert payment["provider"] == "commerce", payment
    assert payment["status"] == "pending", payment
    assert payment["provider_ref"] == "INV-ARNA-00001", payment
    assert payment["booth_id"] == "booth-1", payment
    assert payment["campaign_id"] == "camp-1", payment
    assert float(payment["amount"]) == 50000.0, payment
    details = payment["gateway_payload"]
    assert details["order_id"] == "order-1", details
    assert details["invoice_id"] == "inv-1", details
    assert details["invoice_number"] == "INV-ARNA-00001", details
    assert details["subscription_id"] == "sub-1", details
    assert details["checkout_url"] == "https://checkout.xendit.co/web/inv-1", details
    assert body["charge_url"] == "https://checkout.xendit.co/web/inv-1", body
    pid = payment["id"]
    ok("POST /payments (commerce: order persisted with invoice data)")

    # refresh while unpaid -> stays pending
    r = tclient.post(f"/payments/{pid}/refresh")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "pending", r.text
    ok("POST /payments/{id}/refresh (unpaid -> pending)")

    # refresh after Commerce flips to paid -> succeeded + paid_at
    ROUTES.update(_happy_routes(paid=True))
    r = tclient.post(f"/payments/{pid}/refresh")
    assert r.status_code == 200, r.text
    refreshed = r.json()
    assert refreshed["status"] == "succeeded", refreshed
    assert refreshed["paid_at"] is not None, refreshed
    assert refreshed["gateway_payload"]["order_status"] == "paid", refreshed
    assert refreshed["gateway_payload"]["invoice_status"] == "paid", refreshed
    ok("POST /payments/{id}/refresh (paid -> succeeded + paid_at)")

    # refresh is idempotent on terminal states (no Commerce call needed)
    ROUTES.clear()
    r = tclient.post(f"/payments/{pid}/refresh")
    assert r.status_code == 200 and r.json()["status"] == "succeeded", r.text
    ok("POST /payments/{id}/refresh idempotent on succeeded")

    # cancel a second pending payment (fresh invoice number per order)
    ROUTES.clear()
    ROUTES.update(_happy_routes(n="2"))
    r = tclient.post(
        "/payments",
        json={"device_id": device_id, "campaign_id": "camp-1", "amount": 25000},
    )
    assert r.status_code == 201, r.text
    pid2 = r.json()["payment"]["id"]
    r = tclient.post(f"/payments/{pid2}/cancel")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "failed", r.text
    assert r.json()["gateway_payload"]["cancelled_locally"] is True, r.text
    ok("POST /payments/{id}/cancel (pending -> failed)")

    # campaign exists locally but has no Commerce mapping -> 400, nothing persisted
    with local_session() as db:
        db.add(Campaign(id="camp-9", name="Unmapped Campaign", price=10000))
        db.commit()
    r = tclient.post(
        "/payments",
        json={"device_id": device_id, "campaign_id": "camp-9", "amount": 10000},
    )
    assert r.status_code == 400 and "COMMERCE_OFFERS_JSON" in r.json()["detail"], r.text
    ok("POST /payments unmapped campaign -> 400")

    # token without org claim -> 400
    no_org = {"Authorization": f"Bearer {_make_token()}"}
    r = tclient.post(
        "/payments",
        json={"device_id": device_id, "campaign_id": "camp-1", "amount": 10000},
        headers=no_org,
    )
    assert r.status_code == 400 and "organization_id" in r.json()["detail"], r.text
    ok("POST /payments without org claim -> 400")

    # Commerce 400 (catalog mismatch) surfaces as 400, not 500
    ROUTES.update({("POST", "/orders/"): (400, {"detail": "plan does not belong to product"})})
    r = tclient.post(
        "/payments",
        json={"device_id": device_id, "campaign_id": "camp-1", "amount": 10000},
    )
    assert r.status_code == 400 and "Commerce rejected" in r.json()["detail"], r.text
    ok("Commerce 400 surfaces as 400 with detail")

    # stub provider untouched: refresh/cancel reject non-commerce rows
    os.environ["PAYMENT_PROVIDER"] = "stub"
    r = tclient.post(
        "/payments",
        json={"device_id": device_id, "amount": 1000, "method": "cash"},
    )
    assert r.status_code == 201, r.text
    stub_id = r.json()["payment"]["id"]
    assert r.json()["payment"]["provider"] == "stub"
    r = tclient.post(f"/payments/{stub_id}/refresh")
    assert r.status_code == 400, r.text
    r = tclient.post(f"/payments/{stub_id}/cancel")
    assert r.status_code == 400, r.text
    ok("refresh/cancel reject non-commerce payments (400)")

# offline kiosk + commerce provider -> 503 before any Commerce call
engine.is_online = lambda force=False: False
os.environ["PAYMENT_PROVIDER"] = "commerce"
with TestClient(app, headers=ORG_HEADERS) as tclient:
    r = tclient.get("/devices/me")
    device_id = r.json()["id"]
    ROUTES.clear()  # any Commerce call would raise AssertionError
    r = tclient.post(
        "/payments",
        json={"device_id": device_id, "campaign_id": "camp-1", "amount": 50000},
    )
    assert r.status_code == 503, r.text
    ok("POST /payments (commerce, offline -> 503, no Commerce call)")

# restore process-global patches (other test modules share the interpreter)
engine.is_online = _real_is_online
gateway_mod.CommerceClient = _REAL_GATEWAY_CLIENT
payment_api.CommerceClient = _REAL_API_CLIENT
del os.environ["PAYMENT_PROVIDER"]

print(f"\nALL {PASS} commerce gateway tests passed ({_TMPDIR})")

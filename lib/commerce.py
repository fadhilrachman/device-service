"""Client for the Arna Commerce Core API (https://product.arnatech.id/api/v1).

Checkout flow (mirrors dashboard_arnasite ``src/hooks/use-payments.ts``):

1. ``POST /orders/``                  -> draft order
2. ``POST /orders/{id}/submit/`` (`{}`) -> ``pending_payment`` + invoice + subscription
3. ``POST /orders/{id}/create-payment/`` -> Xendit hosted checkout URL
4. Poll ``GET /orders/{id}/`` (or the invoice) until status is ``paid``.

Auth: the caller's existing Bearer token is forwarded as-is (no separate
service credential). ``organization_id`` is decoded from the JWT payload.
"""

import httpx

from lib.protect_token import decode_base64url_json

# Response keys that may carry the hosted checkout URL. Commerce does not
# document the field name; the site-backend proxy returns ``payment.invoice_url``.
CHECKOUT_URL_KEYS = ("checkout_url", "payment_url", "invoice_url", "redirect_url", "url")

# JWT claim names that may carry the organization / tenant UUID.
ORG_CLAIM_KEYS = ("organization_id", "org_id", "organizationId", "org")
TENANT_CLAIM_KEYS = ("tenant_id", "tenantId")


class CommerceError(Exception):
    """Raised for transport failures and Commerce API error responses."""

    def __init__(self, message: str, status_code: int | None = None, payload=None):
        self.message = message
        self.status_code = status_code
        self.payload = payload
        super().__init__(message)


def _claim(payload: dict, keys: tuple) -> str | None:
    if not isinstance(payload, dict):
        return None
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def extract_organization_id(token_payload: dict) -> str | None:
    """Return the organization UUID from a decoded JWT payload."""
    return _claim(token_payload, ORG_CLAIM_KEYS)


def extract_tenant_id(token_payload: dict) -> str | None:
    """Return the tenant UUID from a decoded JWT payload, if present."""
    return _claim(token_payload, TENANT_CLAIM_KEYS)


def decode_token_payload(raw_token: str) -> dict:
    """Decode a JWT payload without verifying the signature.

    Signature/expiry checks already happened upstream (ProtectTokenMiddleware);
    this is only used to read ``organization_id`` / ``tenant_id`` claims.
    """
    parts = (raw_token or "").split(".")
    if len(parts) != 3:
        return {}
    return decode_base64url_json(parts[1]) or {}


def extract_checkout_url(data) -> str | None:
    """Find the hosted checkout URL in a create-payment response.

    Checks the documented top-level keys first, then one level of nesting
    (``payment`` / ``data``) to cover envelope shapes like
    ``{"payment": {"invoice_url": ...}}``.
    """
    if not isinstance(data, dict):
        return None
    for key in CHECKOUT_URL_KEYS:
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    for nested_key in ("payment", "data"):
        nested = data.get(nested_key)
        if isinstance(nested, dict):
            found = extract_checkout_url(nested)
            if found:
                return found
    return None


def map_commerce_status(order: dict | None, invoice: dict | None = None) -> str:
    """Translate Commerce order/invoice status to the local payment status.

    Local vocabulary: ``pending`` / ``succeeded`` / ``failed``.
    An ``overdue`` invoice is treated as ``failed``: the kiosk payment window
    has passed and the visitor must start a new payment.
    """
    order_status = (order or {}).get("status")
    invoice_status = (invoice or {}).get("status")
    if order_status == "paid" or invoice_status == "paid":
        return "succeeded"
    if order_status == "cancelled" or invoice_status in {"void", "overdue"}:
        return "failed"
    return "pending"


class CommerceClient:
    """Thin wrapper over the Commerce Core REST API (httpx, Bearer auth)."""

    def __init__(
        self,
        bearer_token: str,
        base_url: str = "https://product.arnatech.id/api/v1",
        timeout: float = 30.0,
        transport=None,
    ):
        if not bearer_token or not bearer_token.strip():
            raise CommerceError("Bearer token is required for Commerce API calls.")
        self.base_url = (base_url or "").rstrip("/")
        self._client = httpx.Client(
            base_url=self.base_url,
            headers={
                "Authorization": f"Bearer {bearer_token.strip()}",
                "Content-Type": "application/json",
            },
            timeout=timeout,
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    # -- low-level ------------------------------------------------------
    def _request(self, method: str, path: str, json_body=None, params=None) -> dict:
        try:
            response = self._client.request(method, path, json=json_body, params=params)
        except httpx.HTTPError as exc:
            raise CommerceError(f"Commerce service unreachable: {exc}")
        if response.status_code >= 400:
            raise CommerceError(
                f"Commerce API error {response.status_code}: {_safe_detail(response)}",
                status_code=response.status_code,
                payload=_safe_json(response),
            )
        data = _safe_json(response)
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _oid(value) -> str:
        return value.get("id") if isinstance(value, dict) else None

    # -- checkout -------------------------------------------------------
    def create_order(
        self,
        organization_id: str,
        product: str,
        plan: str,
        price: str,
        tenant_id: str | None = None,
        notes: str | None = None,
    ) -> dict:
        body: dict = {
            "organization_id": organization_id,
            "product": product,
            "plan": plan,
            "price": price,
            "payment_method": "pg",
        }
        if tenant_id:
            body["tenant_id"] = tenant_id
        if notes:
            body["notes"] = notes
        return self._request("POST", "/orders/", json_body=body)

    def submit_order(self, order_id: str) -> dict:
        return self._request("POST", f"/orders/{order_id}/submit/", json_body={})

    def create_payment_session(
        self,
        order_id: str,
        payer_email: str,
        description: str,
        success_url: str,
        failure_url: str,
    ) -> dict:
        return self._request(
            "POST",
            f"/orders/{order_id}/create-payment/",
            json_body={
                "payer_email": payer_email,
                "description": description,
                "success_redirect_url": success_url,
                "failure_redirect_url": failure_url,
            },
        )

    # -- status ----------------------------------------------------------
    def get_order(self, order_id: str) -> dict:
        return self._request("GET", f"/orders/{order_id}/")

    def get_invoice(self, invoice_id: str) -> dict:
        return self._request("GET", f"/invoices/{invoice_id}/")

    def list_invoices(self, organization_id: str | None = None) -> dict:
        params = {"organization_id": organization_id} if organization_id else None
        return self._request("GET", "/invoices/", params=params)

    def cancel_order(self, order_id: str) -> dict:
        return self._request("POST", f"/orders/{order_id}/cancel/", json_body={})


def find_invoice_for_order(client: CommerceClient, organization_id: str, order_id: str) -> dict | None:
    """Locate the invoice created for an order (fallback when submit returns a bare Order)."""
    data = client.list_invoices(organization_id=organization_id)
    results = data.get("results") if isinstance(data, dict) else None
    if not isinstance(results, list):
        return None
    matches = [r for r in results if isinstance(r, dict) and r.get("order") == order_id]
    if not matches:
        return None
    matches.sort(key=lambda r: str(r.get("created_at") or ""))
    return matches[-1]


def start_checkout(
    client: CommerceClient,
    *,
    organization_id: str,
    tenant_id: str | None,
    offer: dict,
    payer_email: str,
    description: str,
    success_url: str,
    failure_url: str,
) -> dict:
    """Run orders -> submit -> create-payment and return normalized checkout data."""
    order = client.create_order(
        organization_id,
        offer["product"],
        offer["plan"],
        offer["price"],
        tenant_id=tenant_id,
        notes=offer.get("description") or description,
    )
    order_id = order.get("id")
    if not order_id:
        raise CommerceError("Commerce /orders/ did not return an order id.", payload=order)

    submitted = client.submit_order(order_id)
    submitted_order = submitted.get("order") if isinstance(submitted.get("order"), dict) else submitted
    order_id = submitted_order.get("id") or order_id

    invoice = submitted.get("invoice") if isinstance(submitted.get("invoice"), dict) else None
    subscription = submitted.get("subscription") if isinstance(submitted.get("subscription"), dict) else None
    if invoice is None:
        invoice = find_invoice_for_order(client, organization_id, order_id)

    invoice = invoice or {}
    session = client.create_payment_session(order_id, payer_email, description, success_url, failure_url)
    checkout_url = extract_checkout_url(session)
    if not checkout_url:
        raise CommerceError(
            "Checkout URL not returned from Commerce payment session.",
            payload={"response_keys": sorted(session.keys())},
        )
    return {
        "order_id": order_id,
        "order": submitted_order,
        "invoice_id": invoice.get("id"),
        "invoice_number": invoice.get("invoice_number"),
        "subscription_id": (subscription or {}).get("id"),
        "checkout_url": checkout_url,
    }


def _safe_json(response: httpx.Response):
    try:
        return response.json()
    except ValueError:
        return None


def _safe_detail(response: httpx.Response) -> str:
    data = _safe_json(response)
    if isinstance(data, dict):
        for key in ("detail", "message", "error"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return str(data)[:300]
    return (response.text or "")[:300]

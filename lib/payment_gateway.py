import os

from dotenv import load_dotenv
from lib.commerce import CommerceClient, CommerceError, start_checkout
from lib.time import wib_now

load_dotenv()

VALID_WEBHOOK_STATUSES = {"pending", "succeeded", "failed"}


class GatewayError(Exception):
    pass


class PaymentGateway:
    """Thin interface so providers (Midtrans/Xendit, ...) can be swapped in later."""

    name = "base"

    def create_charge(self, payment, context: dict | None = None) -> dict:
        """Create a charge for a local Payment row.

        ``context`` carries provider-specific data (e.g. the forwarded Bearer
        token and organization_id for Commerce). Backends that do not need it
        may ignore it.
        """
        raise NotImplementedError

    def parse_webhook(self, payload: dict, headers: dict | None = None) -> dict:
        raise NotImplementedError


class StubGateway(PaymentGateway):
    """Development stub: no real HTTP call, returns a deterministic mock charge."""

    name = "stub"

    def create_charge(self, payment, context: dict | None = None) -> dict:
        return {
            "charge_url": f"http://localhost:8000/payments/{payment.id}/mock-pay",
            "provider_ref": f"stub-{payment.id}",
        }

    def parse_webhook(self, payload: dict, headers: dict | None = None) -> dict:
        provider_ref = payload.get("provider_ref")
        status = payload.get("status", "succeeded")
        if not provider_ref:
            raise GatewayError("Missing provider_ref in payload.")
        if status not in VALID_WEBHOOK_STATUSES:
            raise GatewayError(f"Unknown status: {status}")
        return {
            "provider_ref": provider_ref,
            "status": status,
            "paid_at": wib_now() if status == "succeeded" else None,
            "raw": payload,
        }


def get_gateway() -> PaymentGateway:
    provider = os.getenv("PAYMENT_PROVIDER", "stub").strip().lower()
    if provider == "stub":
        return StubGateway()
    if provider == "commerce":
        return CommerceGateway()
    raise GatewayError(f"Unsupported payment provider: {provider}")


class CommerceGateway(PaymentGateway):
    """Arna Commerce Core API via Xendit hosted checkout.

    Selected with ``PAYMENT_PROVIDER=commerce``. Runs the 3-step checkout
    (orders -> submit -> create-payment) and returns the hosted Xendit URL as
    ``charge_url``. Auth forwards the caller's Bearer token; the Commerce
    catalog offer comes from ``COMMERCE_OFFERS_JSON`` keyed by campaign_id.

    Expected ``context`` keys: ``bearer_token``, ``organization_id``,
    optional ``tenant_id`` / ``offers`` / ``base_url`` / ``timeout`` /
    ``payer_email`` / ``success_url`` / ``failure_url`` / ``transport``
    (the latter two groups exist for configurability and tests).
    """

    name = "commerce"

    def create_charge(self, payment, context: dict | None = None) -> dict:
        # Local import keeps module import order identical to the stub path.
        from config import (
            COMMERCE_BASE_URL,
            COMMERCE_FAILURE_URL,
            COMMERCE_PAYER_EMAIL,
            COMMERCE_SUCCESS_URL,
            COMMERCE_TIMEOUT_SECONDS,
            get_commerce_offers,
        )

        context = context or {}
        bearer_token = context.get("bearer_token")
        organization_id = context.get("organization_id")
        if not bearer_token:
            raise GatewayError("Commerce charge requires bearer_token in context.")
        if not organization_id:
            raise GatewayError(
                "Commerce charge requires organization_id in context "
                "(decoded from the access token)."
            )
        offers = context.get("offers")
        if offers is None:
            offers = get_commerce_offers()
        campaign_key = payment.campaign_id or ""
        offer = offers.get(campaign_key)
        if not offer:
            raise GatewayError(
                f"Campaign '{campaign_key}' is not mapped to a Commerce offer "
                "(COMMERCE_OFFERS_JSON)."
            )
        for key in ("product", "plan", "price"):
            if not offer.get(key):
                raise GatewayError(
                    f"Commerce offer for campaign '{campaign_key}' is missing '{key}'."
                )

        description = (
            offer.get("description")
            or f"Photobooth payment {campaign_key or payment.id}"
        )
        client = CommerceClient(
            bearer_token,
            context.get("base_url") or COMMERCE_BASE_URL,
            timeout=context.get("timeout") or COMMERCE_TIMEOUT_SECONDS,
            transport=context.get("transport"),
        )
        try:
            result = start_checkout(
                client,
                organization_id=organization_id,
                tenant_id=context.get("tenant_id"),
                offer=offer,
                payer_email=context.get("payer_email") or COMMERCE_PAYER_EMAIL,
                description=description,
                success_url=context.get("success_url") or COMMERCE_SUCCESS_URL,
                failure_url=context.get("failure_url") or COMMERCE_FAILURE_URL,
            )
        finally:
            client.close()

        order = result["order"] or {}
        return {
            "charge_url": result["checkout_url"],
            # invoice_number (= Xendit external_id) is unique per invoice.
            "provider_ref": result["invoice_number"] or result["order_id"],
            "details": {
                "order_id": result["order_id"],
                "order_status": order.get("status"),
                "invoice_id": result["invoice_id"],
                "invoice_number": result["invoice_number"],
                "invoice_status": None,
                "subscription_id": result["subscription_id"],
                "checkout_url": result["checkout_url"],
                "offer": {
                    "product": offer["product"],
                    "plan": offer["plan"],
                    "price": offer["price"],
                },
            },
        }
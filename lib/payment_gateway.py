import os

from dotenv import load_dotenv
from lib.time import wib_now

load_dotenv()

VALID_WEBHOOK_STATUSES = {"pending", "succeeded", "failed"}


class GatewayError(Exception):
    pass


class PaymentGateway:
    """Thin interface so providers (Midtrans/Xendit, ...) can be swapped in later."""

    name = "base"

    def create_charge(self, payment) -> dict:
        raise NotImplementedError

    def parse_webhook(self, payload: dict, headers: dict | None = None) -> dict:
        raise NotImplementedError


class StubGateway(PaymentGateway):
    """Development stub: no real HTTP call, returns a deterministic mock charge."""

    name = "stub"

    def create_charge(self, payment) -> dict:
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
    raise GatewayError(f"Unsupported payment provider: {provider}")
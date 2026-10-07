import json
import os

from dotenv import load_dotenv

load_dotenv()


REMOTE_DATABASE_URL = os.getenv(
    "REMOTE_DATABASE_URL",
    "postgresql://postgres:CHANGE_ME@localhost:5432/ourlilphotobooth2",
)

PAYMENT_PROVIDER = os.getenv("PAYMENT_PROVIDER", "stub").strip().lower()
APP_VERSION = os.getenv("APP_VERSION", "0.1.0")

# ===== Arna Payment service / Commerce Core API (PAYMENT_PROVIDER=commerce) =====
# Auth forwards the caller's existing Bearer token; organization_id is decoded
# from that token's JWT payload. payer_email is a placeholder until the kiosk
# collects a real visitor email.
# Payment naming is canonical; COMMERCE_* aliases are kept for backward compat.
PAYMENT_BASE_URL = os.getenv(
    "PAYMENT_BASE_URL",
    os.getenv("COMMERCE_BASE_URL", "https://product.arnatech.id/api/v1"),
).rstrip("/")
PAYMENT_PRODUCT_ID = os.getenv(
    "PAYMENT_PRODUCT_ID", "98d14061-9e07-403e-b1ea-cde54d2dab76"
).strip()
COMMERCE_BASE_URL = os.getenv("COMMERCE_BASE_URL", PAYMENT_BASE_URL).rstrip("/")
COMMERCE_TIMEOUT_SECONDS = float(os.getenv("COMMERCE_TIMEOUT_SECONDS", "30"))
COMMERCE_PAYER_EMAIL = os.getenv("COMMERCE_PAYER_EMAIL", "kiosk@example.com")
COMMERCE_SUCCESS_URL = os.getenv(
    "COMMERCE_SUCCESS_URL", "https://product.arnatech.id/payment/success"
)
COMMERCE_FAILURE_URL = os.getenv(
    "COMMERCE_FAILURE_URL", "https://product.arnatech.id/payment/failed"
)


# ===== WAHA WhatsApp (replaces Twilio) =====
# Free-form text + optional image via the WAHA HTTP API. The sending number is
# whichever account holds the WAHA session; credentials live in .env only
# (see .env.example for the variable list).
WAHA_BASE_URL = os.getenv("WAHA_BASE_URL", "").rstrip("/")
WAHA_API_KEY = os.getenv("WAHA_API_KEY", "").strip()
WAHA_SESSION = os.getenv("WAHA_SESSION", "default").strip() or "default"
WAHA_TIMEOUT_SECONDS = float(os.getenv("WAHA_TIMEOUT_SECONDS", "20"))


def whatsapp_configured() -> bool:
    """True when the WhatsApp sender can be built (base URL + API key present)."""
    return bool(WAHA_BASE_URL and WAHA_API_KEY)


def get_commerce_offers() -> dict:
    """Parse COMMERCE_OFFERS_JSON: {campaign_id: {product, plan, price, description?}}.

    UUIDs come from the Commerce catalog (GET /products/ -> /plans/ -> /prices/).
    """
    raw = os.getenv("COMMERCE_OFFERS_JSON", "").strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except ValueError:
        raise ValueError("COMMERCE_OFFERS_JSON is not valid JSON.")
    if not isinstance(data, dict):
        raise ValueError("COMMERCE_OFFERS_JSON must be a JSON object.")
    return data
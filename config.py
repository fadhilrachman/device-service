import json
import os
import uuid

from dotenv import load_dotenv

load_dotenv()


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


DEVICE_ID = os.getenv("DEVICE_ID", "").strip()
DEVICE_NAME = os.getenv("DEVICE_NAME", "").strip()
DEVICE_CODE = os.getenv("DEVICE_CODE", "").strip()

REMOTE_DATABASE_URL = os.getenv(
    "REMOTE_DATABASE_URL",
    "postgresql://postgres:CHANGE_ME@localhost:5432/ourlilphotobooth2",
)
LOCAL_DB_PATH = os.getenv("LOCAL_DB_PATH", "device.db")

SYNC_INTERVAL_SECONDS = int(os.getenv("SYNC_INTERVAL_SECONDS", "30"))
SYNC_ON_STARTUP = _env_bool("SYNC_ON_STARTUP", True)
PAYMENT_PROVIDER = os.getenv("PAYMENT_PROVIDER", "stub").strip().lower()
APP_VERSION = os.getenv("APP_VERSION", "0.1.0")

# ===== Arna Commerce Core API (PAYMENT_PROVIDER=commerce) =====
# Auth forwards the caller's existing Bearer token; organization_id is decoded
# from that token's JWT payload. payer_email is a placeholder until the kiosk
# collects a real visitor email.
COMMERCE_BASE_URL = os.getenv(
    "COMMERCE_BASE_URL", "https://product.arnatech.id/api/v1"
).rstrip("/")
COMMERCE_TIMEOUT_SECONDS = float(os.getenv("COMMERCE_TIMEOUT_SECONDS", "30"))
COMMERCE_PAYER_EMAIL = os.getenv("COMMERCE_PAYER_EMAIL", "kiosk@example.com")
COMMERCE_SUCCESS_URL = os.getenv(
    "COMMERCE_SUCCESS_URL", "https://product.arnatech.id/payment/success"
)
COMMERCE_FAILURE_URL = os.getenv(
    "COMMERCE_FAILURE_URL", "https://product.arnatech.id/payment/failed"
)


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

_DEVICE_ID_FILE = "device.id"


def _load_persisted_device_id() -> str | None:
    if not os.path.exists(_DEVICE_ID_FILE):
        return None
    try:
        with open(_DEVICE_ID_FILE, "r", encoding="utf-8") as f:
            value = f.read().strip()
            return value or None
    except OSError:
        return None


def _save_persisted_device_id(device_id: str) -> None:
    try:
        with open(_DEVICE_ID_FILE, "w", encoding="utf-8") as f:
            f.write(device_id)
    except OSError:
        pass


def resolve_device_id() -> str:
    """Return the device id, preferring env, then a persisted file, then a new uuid."""
    if DEVICE_ID:
        return DEVICE_ID
    persisted = _load_persisted_device_id()
    if persisted:
        return persisted
    generated = str(uuid.uuid4())
    _save_persisted_device_id(generated)
    return generated
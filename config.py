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
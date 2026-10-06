"""Per-request kiosk liveness bookkeeping.

Runs inside the request (after ProtectTokenMiddleware populated the token
claims) and, for any request carrying a device ``client_id``:

- success (2xx/3xx): ``connectivity = "connect"`` (always overwritten, so the
  vocabulary stays exactly disconnect / connect / error);
- ``last_synced_at`` is stamped too, except for write methods
  (POST/PATCH/PUT/DELETE) and ``GET /devices/sync/status_trigger``;
- error (4xx/5xx): ``connectivity = "error"`` plus one ``device_sync_logs``
  row carrying the API path and the error message.

Everything here is best-effort: bookkeeping must never break the kiosk
response, so all DB work is guarded and failures only log a warning.
"""

import json
import logging

import anyio
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from database import remote_session
from lib.time import wib_now
from models.device import Device
from models.device_sync_log import DeviceSyncLog

logger = logging.getLogger(__name__)

WRITE_METHODS = {"POST", "PATCH", "PUT", "DELETE"}
STATUS_TRIGGER_PATH = "/devices/sync/status_trigger"


def _error_detail(status_code: int, body: bytes) -> str:
    if not body:
        return f"HTTP {status_code}"
    try:
        payload = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        return f"HTTP {status_code}"
    detail = payload.get("detail") if isinstance(payload, dict) else None
    if isinstance(detail, str) and detail.strip():
        return detail.strip()[:500]
    if isinstance(detail, dict) and isinstance(detail.get("message"), str):
        return str(detail["message"]).strip()[:500]
    return f"HTTP {status_code}"


def _record_liveness(
    client_id: str, method: str, path: str, status_code: int, body: bytes
) -> None:
    try:
        with remote_session() as db:
            device = db.query(Device).filter(Device.device_code == client_id.strip()).first()
            if device is None:
                return
            now = wib_now()
            if status_code < 400:
                device.connectivity = "connect"
                if method.upper() == "GET" and path.rstrip("/") != STATUS_TRIGGER_PATH:
                    device.last_synced_at = now
            else:
                device.connectivity = "error"
                db.add(
                    DeviceSyncLog(
                        device_id=device.id,
                        trigger="api",
                        status="failed",
                        error=f"{method.upper()} {path} -> {_error_detail(status_code, body)}",
                        started_at=now,
                        finished_at=now,
                    )
                )
            db.commit()
    except Exception as exc:
        logger.warning("device liveness record failed: %s", exc)


class DeviceLivenessMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        client_id = getattr(request.state, "sso_client_id", None)
        if not isinstance(client_id, str) or not client_id.strip():
            return await call_next(request)
        response = await call_next(request)
        body = getattr(response, "body", b"") or b""
        try:
            await anyio.to_thread.run_sync(
                _record_liveness,
                client_id,
                request.method,
                request.url.path,
                response.status_code,
                bytes(body),
            )
        except Exception as exc:
            logger.warning("device liveness record failed: %s", exc)
        return response

"""Per-request kiosk liveness + sync bookkeeping.

Runs inside the request (after ProtectTokenMiddleware populated the token
claims) and, for any request carrying a device ``client_id``:

- success (2xx/3xx): ``connectivity = "connect"`` (always overwritten, so the
  vocabulary stays exactly disconnect / connect / error);
- a successful GET (except ``GET /devices/sync/status_trigger``, which is just
  polling) also logs one ``device_sync_logs`` row ``type="push"``, the
  server -> kiosk data delivery half, and stamps ``last_synced_at`` (the
  watermark the kiosk diffs against when it pulls config/vouchers);
- error (4xx/5xx): ``connectivity = "error"`` plus one ``device_sync_logs``
  row carrying the API path and the error message: ``type="push"`` for GETs,
  ``type="pull"`` for the bulk sync endpoint, NULL otherwise (``status``
  already says "failed");
- ``POST /sync/bulk`` logs its own row (``type="pull"``) inside the
  endpoint; the request also stamps the device's ``last_synced_at`` there.

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
# The bulk sync lives at /sync/bulk (router prefix "/sync"), not /devices/*.
BULK_PATH = "/sync/bulk"


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


def _log_type(method: str, path: str) -> str | None:
    """Label a failed-request log row by delivery direction.

    GET = the server pushes data to the kiosk; the bulk sync (whatever failed
    method) is the kiosk -> server pull; other writes leave type NULL.
    """
    if method.upper() == "GET":
        return "push"
    if path.rstrip("/") == BULK_PATH:
        return "pull"
    return None


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
                is_push = method.upper() == "GET" and path.rstrip("/") != STATUS_TRIGGER_PATH
                if is_push:
                    device.last_synced_at = now
                    db.add(
                        DeviceSyncLog(
                            device_id=device.id,
                            trigger="api",
                            type="push",
                            status="success",
                            started_at=now,
                            finished_at=now,
                        )
                    )
            else:
                device.connectivity = "error"
                db.add(
                    DeviceSyncLog(
                        device_id=device.id,
                        trigger="api",
                        type=_log_type(method, path),
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

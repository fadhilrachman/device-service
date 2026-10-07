import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse, Response
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session
from urllib.parse import quote

from database import get_db, remote_session
from lib.device_conflict import device_conflict, device_taken, taken_conflict
from lib.sso import SSOClient, SSOError, authorize_payload
from lib.utils import new_device_code
from models.device import Device
from schemas.auth_device import (
    DeviceAuthorizeRequest,
    DeviceAuthorizeResponse,
    DeviceRefreshRequest,
    DeviceRevokeRequest,
    DeviceTokenRequest,
    DeviceTokenResponse,
    DeviceVerificationRequest,
    DeviceVerificationResponse,
)

router = APIRouter(prefix="/auth/device", tags=["auth"])

logger = logging.getLogger(__name__)

# Hardcoded operator verification page. The kiosk QR/manual code always
# points here instead of the verification_uri returned by SSO.
ACCOUNT_DEVICE_VERIFY_URL = "https://account.arnatech.id/id/device/verify"


def _with_account_verify_urls(sso_body: dict) -> dict:
    """Rewrite SSO verification URIs to the hardcoded account page.

    Passthrough when user_code is missing so the flow never breaks.
    """
    user_code = sso_body.get("user_code")
    if not user_code:
        return sso_body
    sso_body["verification_uri"] = ACCOUNT_DEVICE_VERIFY_URL
    sso_body["verification_uri_complete"] = f"{ACCOUNT_DEVICE_VERIFY_URL}?user_code={quote(str(user_code))}"
    return sso_body


def _get_access_token(request: Request) -> str:
    token = getattr(request.state, "sso_access_token", None)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Valid access token is required.")
    return token


def _forward(response) -> Response:
    if response.status_code == status.HTTP_204_NO_CONTENT:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    try:
        body = response.json()
    except Exception:
        body = None
    return JSONResponse(status_code=response.status_code, content=body)


def _sso_reason(response) -> str | None:
    """Readable text out of an SSO error body (dict, list, or plain text)."""
    try:
        body = response.json()
    except Exception:
        body = None
    if isinstance(body, str):
        return body.strip() or None
    if isinstance(body, dict):
        for key in ("detail", "error_description", "message", "error"):
            value = body.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return json.dumps(body, sort_keys=True) if body else None
    return json.dumps(body) if body is not None else None


def _sso_http_error(response) -> HTTPException:
    """Map an SSO non-2xx into an HTTPException that tags the upstream status.

    Mirrors backend2 POST /devices: a 409 from SSO is a pairing conflict, not
    a local unique violation, and the two must never look alike to the caller.
    """
    reason = _sso_reason(response)
    logger.warning(
        "sso authorize rejected: status=%s reason=%s",
        response.status_code,
        reason or getattr(response, "text", "")[:500],
    )
    detail = f"SSO authorize returned {response.status_code}: {reason}" if reason else None
    code = response.status_code
    if code == 404:
        return HTTPException(status_code=404, detail=detail or "Device is not registered with SSO.")
    if code == 409:
        return HTTPException(status_code=409, detail=detail or "Device already authorized.")
    if code == 429:
        return HTTPException(status_code=429, detail=detail or "Too many authorization attempts.")
    if 400 <= code < 500:
        return HTTPException(status_code=400, detail=detail or "SSO rejected the authorize request.")
    return HTTPException(status_code=502, detail=detail or "SSO authorize failed.")


@router.post(
    "/authorize/",
    operation_id="auth_device_authorize_create",
    summary="Device authorization - start",
    status_code=status.HTTP_201_CREATED,
    response_model=DeviceAuthorizeResponse,
    responses={
        400: {"description": "Missing/invalid fields, or the fixed audience or client is not allowed"},
        409: {
            "description": (
                "Device already authorized, or a unique field (tenant_id / "
                "device_code / device_code_sso) is already held by another device"
            )
        },
        429: {"description": "Too many authorization attempts"},
    },
)
def authorize_device(payload: DeviceAuthorizeRequest, db: Session = Depends(get_db)):
    """Create a device row and its SSO grant, all-or-nothing.

    Same concept as backend2 POST /devices, with the kiosk-minimal request
    body kept as-is (``device_name``, ``tenant_id``,
    ``public_key_thumbprint`` only):

    1. Local-first: reject an already-taken ``tenant_id`` and allocate a
       unique ``device_code`` (server-generated, up to 6 tries) before
       touching SSO, so the caller gets the exact field, not a generic
       unique-violation guess.
    2. ``flush`` the new row (no commit yet), then call SSO authorize. The
       DB transaction is held across the SSO call; any SSO failure rolls
       the row back, so a failed authorize never leaves an orphan row
       behind.
    3. Re-check the ``tenant_id`` / ``device_code_sso`` race, bind the SSO
       codes, and commit.

    Success keeps the device-service contract: the raw SSO grant body plus
    the injected ``client_id``, with ``verification_uri`` rewritten to the
    operator account page.
    """
    tenant_id = str(payload.tenant_id)
    # 1. Local-first check-before-write (mirror backend2).
    try:
        if device_taken(db, Device.tenant_id, tenant_id):
            raise taken_conflict("ix_devices_tenant_id")
        device_code: str | None = None
        for _ in range(6):
            candidate = new_device_code()
            if not db.query(Device.id).filter(Device.device_code == candidate).first():
                device_code = candidate
                break
        if not device_code:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Unable to allocate a unique device_code at this time. Retry in a moment.",
            )
        db_obj = Device(device_code=device_code, name=(payload.device_name or device_code)[:160])
        db.add(db_obj)
        try:
            db.flush()
        except IntegrityError as exc:
            db.rollback()
            raise device_conflict(exc)
    except HTTPException:
        db.rollback()
        raise
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Device registry (Neon) is unreachable. Retry when online.",
        )
    # 2. SSO authorize. Any failure rolls back our row (all-or-nothing).
    try:
        response = SSOClient().authorize(
            authorize_payload(
                client_id=db_obj.device_code,
                device_name=payload.device_name,
                tenant_id=tenant_id,
                public_key_thumbprint=payload.public_key_thumbprint,
            )
        )
    except SSOError as exc:
        db.rollback()
        raise HTTPException(status_code=exc.status_code or status.HTTP_502_BAD_GATEWAY, detail=exc.message)
    if not 200 <= response.status_code < 300:
        db.rollback()
        raise _sso_http_error(response)
    try:
        sso_body = response.json()
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="SSO authorize returned an unreadable response.",
        )
    sso_device_code = sso_body.get("device_code") if isinstance(sso_body, dict) else None
    if not sso_device_code:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="SSO authorize response is missing device_code.",
        )
    # 3. Re-check tenant race, bind SSO codes, commit.
    try:
        if device_taken(db, Device.tenant_id, tenant_id, exclude_device_id=db_obj.id):
            db.rollback()
            raise taken_conflict("ix_devices_tenant_id")
        # device_code_sso is only written after the flush above, so its unique
        # index can only be caught here -- check it before committing, not via
        # the exception.
        if device_taken(db, Device.device_code_sso, sso_device_code, exclude_device_id=db_obj.id):
            db.rollback()
            raise taken_conflict("ix_devices_device_code_sso")
        db_obj.tenant_id = tenant_id
        db_obj.device_code_sso = sso_device_code
        db_obj.user_code_sso = sso_body.get("user_code") if isinstance(sso_body, dict) else None
        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            raise device_conflict(exc)
    except HTTPException:
        raise
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Device registry (Neon) is unreachable. Retry when online.",
        )
    db.refresh(db_obj)
    if isinstance(sso_body, dict):
        content = _with_account_verify_urls(dict(sso_body))
        content["client_id"] = db_obj.device_code
        return JSONResponse(status_code=response.status_code, content=content)
    return _forward(response)


@router.post(
    "/verification/",
    operation_id="auth_device_verification_create",
    summary="Device authorization - approve or deny",
    response_model=DeviceVerificationResponse,
    responses={
        400: {"description": "Expired, consumed, denied, or malformed request"},
        403: {"description": "Caller cannot manage devices in this organization"},
    },
)
def verify_device(payload: DeviceVerificationRequest, request: Request):
    try:
        response = SSOClient().verification(
            payload.model_dump(mode="json", exclude_none=True),
            _get_access_token(request),
        )
    except SSOError as exc:
        raise HTTPException(status_code=exc.status_code or status.HTTP_502_BAD_GATEWAY, detail=exc.message)
    return _forward(response)


def _mark_connected(device_code_sso: str) -> None:
    """Mark the device connected + verified on first successful token issuance.

    A 2xx from SSO means the grant was approved, so the pairing is complete:
    flip connectivity to 'connect' and is_verified to True.

    Best-effort by design: token issuance must never break because of these
    flags. Failures are logged; the kiosk keeps polling and a later success
    (or any subsequent success) will set them.
    """
    try:
        with remote_session() as db:
            device = db.query(Device).filter(Device.device_code_sso == device_code_sso).first()
            if device is None:
                return
            if (device.connectivity or "").lower() != "connect":
                device.connectivity = "connect"
            if not device.is_verified:
                device.is_verified = True
            db.commit()
    except Exception as exc:
        logger.warning("failed to mark device connected (sso_code=%s): %s", device_code_sso, exc)


@router.post(
    "/token/",
    operation_id="auth_device_token_create",
    summary="Device authorization - poll for tokens",
    response_model=DeviceTokenResponse,
    responses={
        400: {"description": "authorization_pending, slow_down, access_denied, expired_token, invalid_grant, or unsupported_grant_type"},
    },
)
def device_token(payload: DeviceTokenRequest):
    try:
        response = SSOClient().token(payload.model_dump(mode="json", exclude_none=True))
    except SSOError as exc:
        raise HTTPException(status_code=exc.status_code or status.HTTP_502_BAD_GATEWAY, detail=exc.message)
    if response.status_code == status.HTTP_200_OK:
        _mark_connected(payload.device_code)
    return _forward(response)


@router.post(
    "/refresh/",
    operation_id="auth_device_refresh_create",
    summary="Device authorization - refresh tokens",
    response_model=DeviceTokenResponse,
    responses={
        400: {"description": "invalid_grant - expired, revoked, used, or unknown refresh token"},
    },
)
def refresh_device_token(payload: DeviceRefreshRequest):
    try:
        response = SSOClient().refresh(payload.model_dump(mode="json", exclude_none=True))
    except SSOError as exc:
        raise HTTPException(status_code=exc.status_code or status.HTTP_502_BAD_GATEWAY, detail=exc.message)
    return _forward(response)


@router.post(
    "/revoke/",
    operation_id="auth_device_revoke_create",
    summary="Device authorization - revoke device",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        403: {"description": "Caller cannot revoke this device"},
        404: {"description": "Device not found"},
    },
)
def revoke_device(payload: DeviceRevokeRequest, request: Request):
    try:
        response = SSOClient().revoke(
            payload.model_dump(mode="json", exclude_none=True),
            _get_access_token(request),
        )
    except SSOError as exc:
        raise HTTPException(status_code=exc.status_code or status.HTTP_502_BAD_GATEWAY, detail=exc.message)
    return _forward(response)

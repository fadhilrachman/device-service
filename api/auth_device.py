import logging

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import JSONResponse, Response
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session
from urllib.parse import quote

from database import remote_session
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


def _bind_tenant_on_authorize(
    db: Session, client_id: str, tenant_id: str, sso_device_code: str, sso_user_code: str | None = None
) -> None:
    """Persist tenant_id + SSO codes on the Neon device row.

    The row is located by ``devices.device_code`` matching the SSO
    ``client_id`` from the authorize payload -- device identity never comes
    from env. The row is created on demand when missing (register on
    authorize, same as backend2 POST /devices), otherwise 404 never occurs.
    Authorize is one-time per device: any already-bound device is rejected
    with 409 (resume polling via POST /auth/device/token instead). tenant_id
    stays optional (NULL until first authorize) & unique. Check-before-write:
    every 404/409 rejection happens before any mutation, so a rejected
    authorize never rotates the stored device_code_sso.
    """
    device = db.query(Device).filter(Device.device_code == client_id).first()
    if device is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Device client_id {client_id} is not registered. Pre-register it before authorize.",
        )
    # if device.tenant_id is not None:
    #     if device.tenant_id == tenant_id:
    #         detail = (
    #             "Device already authorized. Resume polling via "
    #             "POST /auth/device/token with the stored device_code."
    #         )
    #     else:
    #         detail = "Device already bound to a tenant."
    #     raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)
    if device_taken(db, Device.tenant_id, tenant_id, exclude_device_id=device.id):
        raise taken_conflict("ix_devices_tenant_id")
    # device_code_sso is unique too, and SSO can hand back a code this registry
    # already stores -- check it here so the commit is not the first to notice.
    if device_taken(db, Device.device_code_sso, sso_device_code, exclude_device_id=device.id):
        raise taken_conflict("ix_devices_device_code_sso")
    if device.tenant_id is None:
        device.tenant_id = tenant_id
    # First and only grant write: re-authorize is rejected above, so the stored
    # device_code never rotates. Resume polling via POST /auth/device/token.
    device.device_code_sso = sso_device_code
    device.user_code_sso = sso_user_code
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise device_conflict(exc)


def _ensure_registered_device(client_id: str, device_name: str) -> str:
    """Find-or-create the Neon device row (register on authorize).

    A missing row is created with ``device_code=client_id`` and
    ``name=device_name`` (status defaults to active) -- same as backend2
    POST /devices, minus the rich detail fields. A concurrent create
    resolves via unique violation: rollback, re-fetch the winner and
    continue. A violation that survives the re-fetch is classified by
    SQLSTATE, so a not-null or foreign-key failure is never reported as a
    duplicate value. Raises 409 only when the device is already bound (one-time
    authorize); uses its own short session (never held across SSO I/O).
    Raises 404 never; 409/503 on bound/unreachable.

    Returns the client_id/device_code that is used for this device row.
    """
    try:
        with remote_session() as db:
            device = db.query(Device).filter(Device.device_code == client_id).first()
            if device is None:
                device = Device(device_code=client_id, name=(device_name or client_id)[:160])
                db.add(device)
                try:
                    db.commit()
                except IntegrityError as exc:
                    db.rollback()
                    device = db.query(Device).filter(Device.device_code == client_id).first()
                    if device is None:
                        raise device_conflict(exc)
            if device.tenant_id is not None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        "Device already authorized. Resume polling via "
                        "POST /auth/device/token with the stored device_code."
                    ),
                )
    except HTTPException:
        raise
    except SQLAlchemyError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Device registry (Neon) is unreachable. Retry when online.",
        )


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
def authorize_device(payload: DeviceAuthorizeRequest):
    # Register-on-authorize (same as backend2 POST /devices): find-or-create
    # the row BEFORE creating an SSO grant, then re-check after SSO to close
    # the concurrent-authorize race.
    client_id_gen = new_device_code()
    try:
        client_id = _ensure_registered_device(client_id_gen, payload.device_name)
    except HTTPException:
        raise
    # Pre-check tenant not bound elsewhere before calling SSO, to mirror backend2
    try:
        with remote_session() as db:
            device = db.query(Device).filter(Device.device_code == client_id).first()
            if device is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Device client_id {client_id} is not registered. Pre-register it before authorize.",
                )
            if device.tenant_id is not None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        "Device already authorized. Resume polling via "
                        "POST /auth/device/token with the stored device_code."
                    ),
                )
            if device_taken(db, Device.tenant_id, str(payload.tenant_id), exclude_device_id=device.id):
                raise taken_conflict("ix_devices_tenant_id")
    except HTTPException:
        raise
    except SQLAlchemyError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Device registry (Neon) is unreachable. Retry when online.",
        )
    try:
        response = SSOClient().authorize(
            authorize_payload(
                client_id=client_id,
                device_name=payload.device_name,
                tenant_id=payload.tenant_id,
                public_key_thumbprint=payload.public_key_thumbprint,
            )
        )
    except SSOError as exc:
        raise HTTPException(status_code=exc.status_code or status.HTTP_502_BAD_GATEWAY, detail=exc.message)
    if not 200 <= response.status_code < 300:
        return _forward(response)
    try:
        sso_body = response.json()
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="SSO authorize returned an unreadable response.",
        )
    sso_device_code = sso_body.get("device_code") if isinstance(sso_body, dict) else None
    if not sso_device_code:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="SSO authorize response is missing device_code.",
        )
    try:
        with remote_session() as db:
            _bind_tenant_on_authorize(
                db,
                client_id,
                str(payload.tenant_id),
                sso_device_code,
                sso_body.get("user_code") if isinstance(sso_body, dict) else None,
            )
    except HTTPException:
        raise
    except SQLAlchemyError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Device registry (Neon) is unreachable. Retry when online.",
        )
    if isinstance(sso_body, dict):
        content = _with_account_verify_urls(dict(sso_body))
        content["client_id"] = client_id
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

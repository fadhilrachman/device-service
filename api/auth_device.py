from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import JSONResponse, Response
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from config import resolve_device_id
from database import remote_session
from lib.sso import SSOClient, SSOError
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


def _bind_tenant_on_authorize(db: Session, tenant_id: str, sso_device_code: str) -> None:
    """Persist tenant_id + device_code_sso on the pre-registered Neon device row.

    First-install registration writes straight to Neon (never SQLite): the row
    must already exist (pre-registered with the DEVICE_ID from env), otherwise
    404. Authorize is one-time per device: any already-bound device is rejected
    with 409 (resume polling via POST /auth/device/token instead). tenant_id
    stays optional (NULL until first authorize) & unique. Check-before-write:
    every 404/409 rejection happens before any mutation, so a rejected
    authorize never rotates the stored device_code_sso.
    """
    device_id = resolve_device_id()
    device = db.get(Device, device_id)
    if device is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Device {device_id} is not registered. Pre-register it before authorize.",
        )
    if device.tenant_id is not None:
        if device.tenant_id == tenant_id:
            detail = (
                "Device already authorized. Resume polling via "
                "POST /auth/device/token with the stored device_code."
            )
        else:
            detail = "Device already bound to a tenant."
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)
    claimed = (
        db.query(Device)
        .filter(Device.tenant_id == tenant_id, Device.id != device.id)
        .first()
    )
    if claimed is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="tenant_id already bound to another device.",
        )
    if device.tenant_id is None:
        device.tenant_id = tenant_id
    # First and only grant write: re-authorize is rejected above, so the stored
    # device_code never rotates. Resume polling via POST /auth/device/token.
    device.device_code_sso = sso_device_code
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="tenant_id already bound to another device.",
        )


def _precheck_authorize_not_bound() -> None:
    """Fast reject before hitting SSO: an already-bound device must not create
    another SSO grant. Uses its own short session (never held across SSO I/O).
    Raises 404/409/503; returns None when the device may proceed to SSO.
    """
    device_id = resolve_device_id()
    try:
        with remote_session() as db:
            device = db.get(Device, device_id)
    except SQLAlchemyError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Device registry (Neon) is unreachable. Retry when online.",
        )
    if device is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Device {device_id} is not registered. Pre-register it before authorize.",
        )
    if device.tenant_id is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Device already authorized. Resume polling via "
                "POST /auth/device/token with the stored device_code."
            ),
        )


@router.post(
    "/authorize/",
    operation_id="auth_device_authorize_create",
    summary="Device authorization - start",
    status_code=status.HTTP_201_CREATED,
    response_model=DeviceAuthorizeResponse,
    responses={
        400: {"description": "Missing/invalid fields or audience not allowed"},
        404: {"description": "Device id is not pre-registered in the registry"},
        409: {"description": "Device already authorized, or tenant bound to another device"},
        429: {"description": "Too many authorization attempts"},
    },
)
def authorize_device(payload: DeviceAuthorizeRequest):
    # One-time authorize: reject bound devices BEFORE creating an SSO grant,
    # then re-check after SSO to close the concurrent-authorize race.
    _precheck_authorize_not_bound()
    try:
        response = SSOClient().authorize(payload.model_dump(mode="json", exclude_none=True))
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
            _bind_tenant_on_authorize(db, str(payload.tenant_id), sso_device_code)
    except HTTPException:
        raise
    except SQLAlchemyError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Device registry (Neon) is unreachable. Retry when online.",
        )
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

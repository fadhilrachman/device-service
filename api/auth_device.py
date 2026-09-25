from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse, Response
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from config import resolve_device_id
from database import get_db
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


def _bind_tenant_on_authorize(db: Session, tenant_id: str) -> None:
    """Persist tenant_id on the local singleton device after SSO authorize succeeds.

    Rules: tenant_id is optional (NULL until first authorize) & unique. A device
    already bound to a different tenant, or a tenant already bound to another
    device, is rejected with 409.
    """
    from sync import engine as sync_engine

    device_id = resolve_device_id()
    device = db.get(Device, device_id)
    if device is None:
        device = sync_engine.ensure_local_device(db)
    if device.tenant_id is not None and device.tenant_id != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Device already bound to a tenant.",
        )
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
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="tenant_id already bound to another device.",
            )


@router.post(
    "/authorize/",
    operation_id="auth_device_authorize_create",
    summary="Device authorization - start",
    status_code=status.HTTP_201_CREATED,
    response_model=DeviceAuthorizeResponse,
    responses={
        400: {"description": "Missing/invalid fields or audience not allowed"},
        429: {"description": "Too many authorization attempts"},
    },
)
def authorize_device(payload: DeviceAuthorizeRequest, db: Session = Depends(get_db)):
    try:
        response = SSOClient().authorize(payload.model_dump(mode="json", exclude_none=True))
    except SSOError as exc:
        raise HTTPException(status_code=exc.status_code or status.HTTP_502_BAD_GATEWAY, detail=exc.message)
    if 200 <= response.status_code < 300:
        _bind_tenant_on_authorize(db, str(payload.tenant_id))
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

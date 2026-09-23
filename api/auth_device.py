from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import JSONResponse, Response

from lib.sso import SSOClient, SSOError
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
def authorize_device(payload: DeviceAuthorizeRequest):
    try:
        response = SSOClient().authorize(payload.model_dump(mode="json", exclude_none=True))
    except SSOError as exc:
        raise HTTPException(status_code=exc.status_code or status.HTTP_502_BAD_GATEWAY, detail=exc.message)
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

import base64
import json
import time
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from fastapi.security import HTTPBearer


PUBLIC_PATHS = {
    "/",
    "/docs",
    "/redoc",
    "/openapi.json",
    # Device authorization onboarding is called by the unauthenticated kiosk.
    "/auth/device/authorize",
    "/auth/device/authorize/",
    "/auth/device/token",
    "/auth/device/token/",
    "/auth/device/refresh",
    "/auth/device/refresh/",
}
bearer_scheme = HTTPBearer(auto_error=False)


def unauthorized(message: str) -> JSONResponse:
    return JSONResponse(
        status_code=401,
        content={"error": "unauthorized", "message": message},
    )


def decode_base64url_json(value: str) -> dict[str, Any] | None:
    try:
        padding = "=" * (-len(value) % 4)
        decoded = base64.urlsafe_b64decode(value + padding).decode("utf-8")
        result = json.loads(decoded)
        return result if isinstance(result, dict) else None
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
        return None


class ProtectTokenMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        if request.url.path in PUBLIC_PATHS or request.url.path.startswith(("/docs/", "/redoc/")):
            return await call_next(request)

        authorization = request.headers.get("authorization")

        if not authorization:
            return unauthorized("Authorization header is required.")

        authorization_parts = authorization.split(" ")
        if len(authorization_parts) != 2 or authorization_parts[0] != "Bearer" or not authorization_parts[1]:
            return unauthorized("Authorization header must use Bearer token.")

        token_parts = authorization_parts[1].split(".")
        if len(token_parts) != 3:
            return unauthorized("Invalid token format.")

        header = decode_base64url_json(token_parts[0])
        payload = decode_base64url_json(token_parts[1])

        if header is None or payload is None:
            return unauthorized("Invalid token payload.")

        now_in_seconds = int(time.time())
        expiration = payload.get("exp")

        # if isinstance(expiration, bool) or not isinstance(expiration, (int, float)):
        #     return unauthorized("Token expiration is required.")

        # if expiration <= now_in_seconds:
        #     return unauthorized("Token has expired.")

        user_id = payload.get("user_id")
        if not isinstance(user_id, str) or len(user_id) == 0:
            return unauthorized("Token user_id is required.")

        request.state.sso_user_id = user_id
        request.state.sso_org_id = payload.get("org_id")
        request.state.sso_token_header = header
        request.state.sso_token_payload = payload
        request.state.sso_access_token = authorization_parts[1]

        return await call_next(request)
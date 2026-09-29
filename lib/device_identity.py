from fastapi import HTTPException, Request, status


def require_request_device_id(request: Request) -> str:
    """Return the calling device's id from its decoded access token.

    The device identity is never taken from env or request bodies: it is the
    ``device_id`` claim of the Bearer token (populated by
    ProtectTokenMiddleware). Operator tokens carry no such claim, so calling
    this from an operator-only endpoint fails closed with 401.
    """
    device_id = getattr(request.state, "sso_device_id", None)
    if not isinstance(device_id, str) or not device_id.strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="device_id claim is missing in the access token.",
        )
    return device_id.strip()

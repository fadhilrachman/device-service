from fastapi import HTTPException, Request, status
from sqlalchemy.orm import Session

from models.device import Device


def require_request_device_id(db: Session, request: Request) -> str:
    """Return the calling device's id, resolved from its access token.

    The device identity is never taken from env or request bodies: it is the
    ``client_id`` claim of the Bearer token (populated by
    ProtectTokenMiddleware), resolved against ``devices.device_code``.
    Operator tokens carry no such claim, so calling this from an
    operator-only endpoint fails closed with 401, as does an unknown
    client_id.
    """
    client_id = getattr(request.state, "sso_client_id", None)
    if not isinstance(client_id, str) or not client_id.strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="client_id claim is missing in the access token.",
        )
    device = db.query(Device).filter(Device.device_code == client_id.strip()).first()
    if device is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unknown device client_id in the access token.",
        )
    return device.id

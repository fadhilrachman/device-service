from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from config import whatsapp_configured
from database import get_db
from lib.device_identity import require_request_device_id
from lib.waha import WahaClient, WahaError
from lib.whatsapp import normalize_recipient
from schemas.whatsapp import WhatsAppSendRequest, WhatsAppSendResponse

router = APIRouter(prefix="/whatsapp", tags=["whatsapp"])


def get_whatsapp_client() -> WahaClient:
    """Swappable seam: tests override this instead of calling WAHA."""
    return WahaClient()


@router.post(
    "/send",
    response_model=WhatsAppSendResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Send a WhatsApp message to a visitor",
    description=(
        "Send free-form text (plus an optional image) through the configured "
        "WAHA session (WAHA_SESSION). Device comes from the Bearer "
        "token and is echoed back for audit."
    ),
    responses={
        400: {"description": "to is not a valid WhatsApp address, or text is empty"},
        401: {"description": "Missing or unknown client_id claim in the access token"},
        502: {"description": "WAHA rejected the send or is unreachable"},
        503: {"description": "WhatsApp is not configured (missing WAHA base URL or API key)"},
    },
)
def send_whatsapp_message(
    payload: WhatsAppSendRequest,
    request: Request,
    client: WahaClient = Depends(get_whatsapp_client),
    db: Session = Depends(get_db),
):
    device_id = require_request_device_id(db, request)
    try:
        to = normalize_recipient(payload.to)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    if not whatsapp_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="WhatsApp is not configured: WAHA_BASE_URL / WAHA_API_KEY are missing.",
        )
    try:
        if payload.image_url:
            result = client.send_image(to, payload.image_url, payload.text)
        else:
            result = client.send_text(to, payload.text)
    except WahaError as exc:
        # Upstream 4xx means our request is wrong (502 for the kiosk:
        # it is not the caller's fault and it must not retry blindly).
        upstream = exc.status_code or 0
        code = (
            status.HTTP_400_BAD_REQUEST
            if 400 <= upstream < 500
            else status.HTTP_502_BAD_GATEWAY
        )
        raise HTTPException(status_code=code, detail=exc.message)
    return WhatsAppSendResponse(
        message_sid=result.get("sid"),
        status=result.get("status"),
        to=result.get("to") or to,
        from_number=result.get("from") or client.session,
        device_id=device_id,
    )

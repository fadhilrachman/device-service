from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from config import whatsapp_configured
from database import get_db
from lib.device_identity import require_request_device_id
from lib.whatsapp import WhatsAppClient, WhatsAppError, normalize_recipient
from schemas.whatsapp import WhatsAppSendRequest, WhatsAppSendResponse

router = APIRouter(prefix="/whatsapp", tags=["whatsapp"])


def get_whatsapp_client() -> WhatsAppClient:
    """Swappable seam: tests override this instead of calling Twilio."""
    return WhatsAppClient()


@router.post(
    "/send",
    response_model=WhatsAppSendResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Send the WhatsApp content template to a visitor",
    description=(
        "Send the approved Twilio WhatsApp content template configured for this deployment "
        "(TWILIO_WHATSAPP_CONTENT_SID) from TWILIO_WHATSAPP_FROM. Device comes from the Bearer "
        "token and is echoed back for audit. The message body is fixed by the template; only the "
        "placeholder values travel in content_variables."
    ),
    responses={
        400: {"description": "to is not a valid WhatsApp address"},
        401: {"description": "Missing or unknown client_id claim in the access token"},
        502: {"description": "Twilio rejected the send or is unreachable"},
        503: {"description": "WhatsApp is not configured (missing credentials or SDK)"},
    },
)
def send_whatsapp_message(
    payload: WhatsAppSendRequest,
    request: Request,
    client: WhatsAppClient = Depends(get_whatsapp_client),
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
            detail="WhatsApp is not configured: TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN are missing.",
        )
    try:
        result = client.send_template(to, payload.content_variables)
    except WhatsAppError as exc:
        # Upstream 4xx means our request/template is wrong (502 for the kiosk:
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
        from_number=result.get("from") or client.from_address,
        device_id=device_id,
    )
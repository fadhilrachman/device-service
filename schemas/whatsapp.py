from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class WhatsAppSendRequest(BaseModel):
    """Send the configured WhatsApp content template to one visitor number."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "to": "whatsapp:+62881022077883",
                "content_variables": {"1": "https://storage.arnatech.id/files/abc.jpg"},
            }
        }
    )

    to: str = Field(
        description="Visitor number in WhatsApp address format (whatsapp:+628…). Plain +62… and spaced/dashed input are normalized. 8-15 digits required.",
    )
    content_variables: Optional[dict[str, str]] = Field(
        default=None,
        description="Twilio template variables keyed by placeholder number ({\"1\": \"value\"}). Must match the approved template; the template body itself is fixed server-side.",
    )


class WhatsAppSendResponse(BaseModel):
    message_sid: str = Field(description="Twilio message SID, for support/debugging.")
    status: Optional[str] = Field(default=None, description="Twilio message status, usually queued.")
    to: str
    from_number: str
    device_id: str = Field(description="Kiosk that requested the send (from the access token).")
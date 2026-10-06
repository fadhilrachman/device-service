from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class WhatsAppSendRequest(BaseModel):
    """Send free-form text (+ optional image) to one visitor number via WAHA."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "to": "whatsapp:+62881022077883",
                "text": "Your photo is ready! Download it here: https://example.com/p/abc",
                "image_url": "https://storage.arnatech.id/files/abc.jpg",
            }
        }
    )

    to: str = Field(
        description="Visitor number in WhatsApp address format (whatsapp:+628…). Plain +62… and spaced/dashed input are normalized. 8-15 digits required.",
    )
    text: str = Field(
        min_length=1,
        description="Message text. Used as the message body, or as the image caption when image_url is set.",
    )
    image_url: Optional[str] = Field(
        default=None,
        description="Optional public image URL. When set, the message is sent as an image with text as caption.",
    )


class WhatsAppSendResponse(BaseModel):
    message_sid: Optional[str] = Field(default=None, description="WAHA message id, for support/debugging.")
    status: Optional[str] = Field(default=None, description="Send status, usually sent.")
    to: str
    from_number: str = Field(description="WAHA session the message was sent from.")
    device_id: str = Field(description="Kiosk that requested the send (from the access token).")

"""Twilio WhatsApp sender.

Thin wrapper around `twilio.rest.Client` so the API layer stays testable: the
Twilio SDK is imported lazily (constructing the client never needs the network)
and every failure comes back as `WhatsAppError` with the upstream status code.
"""

import re

from config import (
    TWILIO_ACCOUNT_SID,
    TWILIO_AUTH_TOKEN,
    TWILIO_TIMEOUT_SECONDS,
    TWILIO_WHATSAPP_CONTENT_SID,
    TWILIO_WHATSAPP_FROM,
)

WHATSAPP_ADDRESS_RE = re.compile(r"^whatsapp:\+\d{8,15}$")


class WhatsAppError(Exception):
    """Twilio call failed. `status_code` is the upstream HTTP status, if any."""

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def normalize_recipient(value: str) -> str:
    """Accept `+628…`, `whatsapp:+628…` or spaced/dashed input.

    Returns the canonical `whatsapp:+<E.164>` address or raises ValueError.
    """
    raw = (value or "").strip()
    if raw.lower().startswith("whatsapp:"):
        raw = raw[len("whatsapp:"):]
    digits = re.sub(r"[\s\-()]", "", raw)
    if not digits.startswith("+") or not re.fullmatch(r"\+\d{8,15}", digits):
        raise ValueError(
            "to must be a WhatsApp address like whatsapp:+62881022077883"
        )
    address = f"whatsapp:{digits}"
    if not WHATSAPP_ADDRESS_RE.match(address):  # defensive, same rule as above
        raise ValueError("to must be a WhatsApp address like whatsapp:+62881022077883")
    return address


class WhatsAppClient:
    """Sends a reviewed WhatsApp content template to one recipient."""

    def __init__(
        self,
        account_sid: str | None = None,
        auth_token: str | None = None,
        from_address: str | None = None,
        content_sid: str | None = None,
        timeout: float | None = None,
    ):
        self.account_sid = account_sid or TWILIO_ACCOUNT_SID
        self.auth_token = auth_token or TWILIO_AUTH_TOKEN
        self.from_address = from_address or TWILIO_WHATSAPP_FROM
        self.content_sid = content_sid or TWILIO_WHATSAPP_CONTENT_SID
        self.timeout = TWILIO_TIMEOUT_SECONDS if timeout is None else timeout
        self._client = None

    @property
    def client(self):
        if self._client is None:
            try:
                from twilio.rest import Client  # imported lazily on purpose
            except ImportError as exc:  # pragma: no cover - depends on install
                raise WhatsAppError(
                    "Twilio SDK is not installed. Add twilio to requirements.txt."
                ) from exc
            self._client = Client(self.account_sid, self.auth_token)
        return self._client

    def send_template(
        self, to: str, content_variables: dict | None = None
    ) -> dict:
        """Send the configured template. Returns Twilio's message summary."""
        try:
            message = self.client.messages.create(
                to=to,
                from_=self.from_address,
                content_sid=self.content_sid,
                content_variables=content_variables or None,
                timeout=self.timeout,
            )
        except WhatsAppError:
            raise
        except Exception as exc:  # TwilioRestError, network errors, ...
            status_code = getattr(exc, "status", None) or getattr(exc, "code", None)
            raise WhatsAppError(str(exc), status_code=status_code) from exc
        return {
            "sid": getattr(message, "sid", None),
            "status": getattr(message, "status", None),
            "to": getattr(message, "to", to),
            "from": getattr(message, "from_", self.from_address),
        }
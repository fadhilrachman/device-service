"""WAHA WhatsApp sender (replaces Twilio).

Thin wrapper around the WAHA HTTP API (https://waha.arnatech.id) so the API
layer stays testable: HTTP goes through httpx (already a dependency) and
every failure comes back as a ``WahaError`` with the upstream status code.
"""

import httpx

from config import (
    WAHA_API_KEY,
    WAHA_BASE_URL,
    WAHA_SESSION,
    WAHA_TIMEOUT_SECONDS,
)


class WahaError(Exception):
    """WAHA call failed. `status_code` is the upstream HTTP status, if any."""

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def to_chat_id(address: str) -> str:
    """Convert a ``whatsapp:+628…`` address to a WAHA chat id (``628…@c.us``)."""
    digits = address
    if digits.lower().startswith("whatsapp:"):
        digits = digits[len("whatsapp:") :]
    digits = digits.strip()
    if digits.startswith("+"):
        digits = digits[1:]
    return f"{digits}@c.us"


class WahaClient:
    """Sends free-form text (+ optional image) through one WAHA session."""

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        session: str | None = None,
        timeout: float | None = None,
    ):
        self.base_url = (base_url or WAHA_BASE_URL).rstrip("/")
        self.api_key = api_key if api_key is not None else WAHA_API_KEY
        self.session = session or WAHA_SESSION
        self.timeout = WAHA_TIMEOUT_SECONDS if timeout is None else timeout

    def _post(self, path: str, body: dict) -> dict:
        try:
            response = httpx.post(
                f"{self.base_url}{path}",
                json=body,
                headers={"X-Api-Key": self.api_key, "Content-Type": "application/json"},
                timeout=self.timeout,
            )
        except httpx.HTTPError as exc:
            raise WahaError(f"WAHA service unreachable: {exc}") from exc
        if response.status_code >= 400:
            detail = response.text[:300]
            try:
                detail = response.json().get("message", detail)
            except Exception:
                pass
            raise WahaError(f"WAHA rejected the request: {detail}", status_code=response.status_code)
        try:
            return response.json()
        except Exception as exc:
            raise WahaError("WAHA returned an unreadable response.") from exc

    def send_text(self, to: str, text: str) -> dict:
        """Send a text message. Returns a Twilio-shaped summary for callers."""
        body = self._post(
            "/api/sendText",
            {"session": self.session, "chatId": to_chat_id(to), "text": text},
        )
        return {
            "sid": body.get("id"),
            "status": "sent",
            "to": to,
            "from": self.session,
        }

    def send_image(self, to: str, image_url: str, caption: str | None = None) -> dict:
        """Send an image URL with an optional caption as text."""
        payload: dict = {
            "session": self.session,
            "chatId": to_chat_id(to),
            "file": {"url": image_url},
        }
        if caption:
            payload["caption"] = caption
        body = self._post("/api/sendImage", payload)
        return {
            "sid": body.get("id"),
            "status": "sent",
            "to": to,
            "from": self.session,
        }

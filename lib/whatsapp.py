"""WhatsApp recipient normalization (provider-agnostic).

The actual sending lives in lib/waha.py (WAHA HTTP API).
"""

import re


WHATSAPP_ADDRESS_RE = re.compile(r"^whatsapp:\+\d{8,15}$")


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

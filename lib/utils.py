import secrets
import uuid


def new_id() -> str:
    return str(uuid.uuid4())


# Human-friendly voucher codes without ambiguous characters (0/O/1/I).
VOUCHER_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


def new_voucher_code() -> str:
    chars = "".join(secrets.choice(VOUCHER_ALPHABET) for _ in range(8))
    return f"{chars[:4]}-{chars[4:]}"
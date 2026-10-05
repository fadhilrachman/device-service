import secrets
import uuid

# Device code alphabet avoids visually ambiguous characters (0/O/1/I) and
# keeps codes easy to read when typed manually by the operator.
DEVICE_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


def new_id() -> str:
    return str(uuid.uuid4())


def new_device_code(prefix: str = "BE-") -> str:
    """Generate a short, collision-resistant device code.

    Codes are deterministic in format (prefix + 8 random chars) and must stay
    under the device_code column width (100). 8 characters gives ~5e14
    possibilities, enough to retry a few times on the rare collision without
    leaking a predictable sequence.
    """
    suffix = "".join(secrets.choice(DEVICE_CODE_ALPHABET) for _ in range(8))
    return f"{prefix}{suffix}"


# Human-friendly voucher codes without ambiguous characters (0/O/1/I).
VOUCHER_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


def new_voucher_code() -> str:
    chars = "".join(secrets.choice(VOUCHER_ALPHABET) for _ in range(8))
    return f"{chars[:4]}-{chars[4:]}"

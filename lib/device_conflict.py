"""Integrity-conflict handling for the `devices` table.

`devices` carries five unique indexes, and every writer used to collapse a
violation into one generic "already in use" message that named the wrong field
most of the time. Classification is by SQLSTATE rather than constraint name
because a not-null violation (23502) leaves `diag.constraint_name` empty: keying
off the name alone reported a missing column as a duplicate value. Only
`pgcode == 23505` is ever described as a unique violation.

Mirrors backend2/api/device.py -- same table, same index names.
"""

import logging
import re

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from models.device import Device

logger = logging.getLogger(__name__)

SQLSTATE_UNIQUE = "23505"
SQLSTATE_FOREIGN_KEY = "23503"
SQLSTATE_NOT_NULL = "23502"
SQLSTATE_STRING_TOO_LONG = "22001"
SQLITE_UNIQUE_MARKER = "UNIQUE constraint failed"

# One entry per unique index on `devices`.
DEVICE_CONSTRAINT_MESSAGES = {
    "ix_devices_device_code": "device_code is already registered to another device.",
    "ix_devices_tenant_id": "tenant_id is already bound to another device.",
    "ix_devices_device_code_sso": "SSO device_code is already bound to another device.",
    "uq_devices_camera_profile_id": "camera_profile_id is already assigned to another device.",
    "uq_devices_printer_profile_id": "printer_profile_id is already assigned to another device.",
}
DEVICE_FOREIGN_KEY_MESSAGES = {
    "devices_camera_profile_id_fkey": "camera_profile_id does not reference an existing camera profile.",
    "devices_printer_profile_id_fkey": "printer_profile_id does not reference an existing printer profile.",
}
DEVICE_INTEGRITY_FALLBACK = "Database constraint violation."

# Postgres reports the index name; SQLite only names the column. Longest key
# first so `device_code_sso` is never swallowed by the `device_code` prefix.
DEVICE_COLUMN_CONSTRAINTS = {
    "device_code_sso": "ix_devices_device_code_sso",
    "camera_profile_id": "uq_devices_camera_profile_id",
    "printer_profile_id": "uq_devices_printer_profile_id",
    "device_code": "ix_devices_device_code",
    "tenant_id": "ix_devices_tenant_id",
}
NOT_NULL_COLUMN_RE = re.compile(r"null value in column (\S+)")


def _diag_of(exc: IntegrityError):
    return getattr(exc.orig, "diag", None)


def sqlstate(exc: IntegrityError) -> str:
    """Postgres SQLSTATE, or "" on drivers that do not expose one (SQLite)."""
    return getattr(_diag_of(exc), "sqlstate", None) or getattr(exc.orig, "pgcode", None) or ""


def constraint_name(exc: IntegrityError) -> str | None:
    """Index/constraint name the database rejected, or None if it carries none."""
    name = getattr(_diag_of(exc), "constraint_name", None)
    if name:
        return name
    # Fallback: some drivers only surface the offending key in the message text.
    message = str(exc.orig)
    for candidate in DEVICE_CONSTRAINT_MESSAGES:
        if candidate in message:
            return candidate
    for column, constraint in DEVICE_COLUMN_CONSTRAINTS.items():
        if f"devices.{column}" in message:
            return constraint
    return None


def conflict_detail(exc: IntegrityError) -> str:
    """Message that describes the class of failure, not a guess."""
    message = str(exc.orig)
    state = sqlstate(exc)
    constraint = constraint_name(exc)
    is_unique = state == SQLSTATE_UNIQUE or (not state and SQLITE_UNIQUE_MARKER in message)
    if is_unique:
        if constraint in DEVICE_CONSTRAINT_MESSAGES:
            return DEVICE_CONSTRAINT_MESSAGES[constraint]
        if constraint:
            return f"Duplicate value violates unique constraint {constraint}."
        return "Duplicate value violates a unique constraint."
    if state == SQLSTATE_NOT_NULL:
        match = NOT_NULL_COLUMN_RE.search(message)
        column = getattr(_diag_of(exc), "column_name", None) or (match.group(1).strip("\"'") if match else None)
        return f"{column} is required and must not be null." if column else "A required column was null."
    if state == SQLSTATE_FOREIGN_KEY:
        return DEVICE_FOREIGN_KEY_MESSAGES.get(
            constraint, f"Foreign key constraint {constraint} was violated."
        )
    if state == SQLSTATE_STRING_TOO_LONG:
        return "A submitted value is longer than its column allows."
    return DEVICE_INTEGRITY_FALLBACK


def device_conflict(exc: IntegrityError) -> HTTPException:
    """409 that names what the database actually rejected."""
    logger.warning(
        "device integrity error: sqlstate=%s constraint=%s",
        sqlstate(exc) or "unknown",
        constraint_name(exc),
        exc_info=exc,
    )
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=conflict_detail(exc))


def device_taken(db: Session, column, value, *, exclude_device_id: str | None = None) -> bool:
    """True when another device already holds `value` in the unique `column`."""
    if value is None:
        return False
    query = db.query(Device.id).filter(column == value)
    if exclude_device_id is not None:
        query = query.filter(Device.id != exclude_device_id)
    return query.first() is not None


def taken_conflict(constraint: str) -> HTTPException:
    """409 built from a known constraint name, for check-before-write paths."""
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=DEVICE_CONSTRAINT_MESSAGES[constraint],
    )

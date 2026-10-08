"""Soft-delete convention: every table carries ``deleted_at`` (NULL = active).

Mirrors backend2/lib/soft_delete.py -- both services share one Postgres, and
backend2 owns the migrations. Rules:
- Operational reads (kiosk config/sync/session/voucher) treat deleted rows
  as missing via ``active()`` / ``get_active_or_404``.
- History reads join without the filter so past records keep resolving.
- Nothing here ever calls ``db.delete()`` on these tables.
"""

from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import DateTime
from sqlalchemy.orm import Mapped, mapped_column

from lib.time import wib_now


def deleted_at_column() -> Mapped[datetime | None]:
    """Nullable soft-delete timestamp shared by every table."""
    return mapped_column(DateTime, nullable=True, index=True)


def soft_delete(db_obj) -> None:
    """Mark a row as deleted (idempotent). Never call ``db.delete()``."""
    if getattr(db_obj, "deleted_at", None) is None:
        db_obj.deleted_at = wib_now()


def restore(db_obj) -> None:
    """Undo a soft-delete."""
    if hasattr(db_obj, "deleted_at"):
        db_obj.deleted_at = None


def is_deleted(db_obj) -> bool:
    return getattr(db_obj, "deleted_at", None) is not None


def active(model):
    """SQLAlchemy filter expression matching non-deleted rows of ``model``."""
    return model.deleted_at.is_(None)


def get_active_or_404(db, model, id: str, label: str):
    """Fetch by PK, treating soft-deleted rows as missing (for write paths)."""
    db_obj = db.get(model, id)
    if db_obj is None or is_deleted(db_obj):
        raise HTTPException(status_code=404, detail=f"{label} not found")
    return db_obj

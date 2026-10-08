from datetime import datetime

from sqlalchemy.orm import Session

from lib.time import WIB_TZ, wib_now
from models.device_assignment import DeviceAssignment


def _as_naive_wib(dt: datetime) -> datetime:
    """Normalize a stored bound to naive WIB for comparison.

    App convention is naive-WIB datetimes (see ``wib_now``): those are used
    as-is. Only tz-aware values (e.g. PostgreSQL timestamptz round-trips)
    are converted. NOTE: this deliberately differs from ``to_wib``, which
    treats naive input as UTC.
    """
    if dt.tzinfo is not None:
        return dt.astimezone(WIB_TZ).replace(tzinfo=None)
    return dt


def is_assignment_window_valid(assignment: DeviceAssignment | None, now=None) -> bool:
    """True when the assignment may currently serve the device.

    Rules: status must be "active", both ``assigned_from`` and
    ``assigned_until`` must be set (NULL on either side means the window is
    undefined -> not valid), and ``now`` must fall inside
    ``[assigned_from, assigned_until]`` (inclusive). Stored datetimes may be
    tz-aware (PostgreSQL timestamptz) while the app compares naive WIB, so
    bounds are normalized with :func:`to_wib` first.
    """
    if assignment is None or assignment.status != "active":
        return False
    if assignment.deleted_at is not None:
        return False
    booth = assignment.booth
    if booth is not None and booth.deleted_at is not None:
        return False
    if assignment.assigned_from is None or assignment.assigned_until is None:
        return False
    now = now or wib_now()
    start = _as_naive_wib(assignment.assigned_from)
    end = _as_naive_wib(assignment.assigned_until)
    return start <= now <= end


def get_valid_assignment(db: Session, device_id: str) -> DeviceAssignment | None:
    """Return the device's currently-valid assignment, if any.

    Latest ``assigned_from`` first: when several active rows exist, the
    newest one whose window covers now wins. Rows with an open/expired
    window are skipped (never auto-mutated here).
    """
    candidates = (
        db.query(DeviceAssignment)
        .filter(
            DeviceAssignment.device_id == device_id,
            DeviceAssignment.status == "active",
            DeviceAssignment.deleted_at.is_(None),
        )
        .order_by(DeviceAssignment.assigned_from.desc())
        .all()
    )
    now = wib_now()
    for assignment in candidates:
        if is_assignment_window_valid(assignment, now):
            return assignment
    return None

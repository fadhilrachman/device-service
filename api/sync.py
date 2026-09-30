from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from api.session import _snapshot_payload
from database import get_db
from lib.device_identity import require_request_device_id
from lib.time import wib_now
from models.booth import Booth
from models.campaign import Campaign
from models.device import Device
from models.device_sync_log import DeviceSyncLog
from models.frame_template import FrameTemplate
from models.payment import Payment
from models.session import ActivationMode, SessionModel, SessionState
from models.session_device_log import SessionDeviceLog
from models.voucher import Voucher
from schemas.sync import (
    MAX_BULK_ITEMS,
    BulkRecordResult,
    BulkSummary,
    BulkSyncRequest,
    BulkSyncResponse,
)

router = APIRouter(prefix="/sync", tags=["sync"])

MAX_ERRORS_PER_TABLE = 10


def _fail(tables: dict, table: str, message: str) -> None:
    entry = tables[table]
    entry["failed"] += 1
    if len(entry["errors"]) < MAX_ERRORS_PER_TABLE:
        entry["errors"].append(message[:200])


def _parse_state(value: str) -> SessionState:
    try:
        return SessionState(value)
    except ValueError:
        raise ValueError(f"invalid session state '{value}'")


def _parse_activation(value: str | None):
    if value is None:
        return None
    try:
        return ActivationMode(value)
    except ValueError:
        raise ValueError(f"invalid activation_mode '{value}'")


def _resolve_frame(db: Session, frame_id: str | None) -> str | None:
    if not frame_id:
        return None
    if frame_id.startswith("frm_"):
        return None  # kiosk-local frame, not a server row
    if not db.get(FrameTemplate, frame_id):
        raise ValueError(f"frame_template {frame_id} not found")
    return frame_id


def _checked_ref(db: Session, model, ref_id: str | None, label: str) -> str | None:
    if ref_id is None:
        return None
    if not db.get(model, ref_id):
        raise ValueError(f"{label} {ref_id} not found")
    return ref_id


def _upsert_session(db: Session, device: Device, item) -> tuple[str, bool]:
    """Insert or refresh a session by session_local_id. Returns (id, changed)."""
    state = _parse_state(item.state)
    activation = _parse_activation(item.activation_mode)
    frame_id = _resolve_frame(db, item.frame_template_id)
    booth_id = _checked_ref(db, Booth, item.booth_id, "booth")
    campaign_id = _checked_ref(db, Campaign, item.campaign_id, "campaign")

    existing = (
        db.query(SessionModel).filter(SessionModel.client_ref == item.session_local_id).first()
    )
    if existing is None:
        obj = SessionModel(
            client_ref=item.session_local_id,
            device_id=device.id,
            booth_id=booth_id,
            campaign_id=campaign_id,
            frame_template_id=frame_id,
            activation_mode=activation,
            state=state,
            offline=item.offline,
        )
        if item.created_at is not None:
            obj.created_at = item.created_at
        db.add(obj)
        db.flush()
        _write_synced_log(db, obj, device)
        return obj.id, True

    if existing.device_id != device.id:
        raise ValueError(f"session_local_id {item.session_local_id} belongs to another device")
    changed = (
        existing.state != state
        or existing.frame_template_id != frame_id
        or existing.activation_mode != activation
        or existing.booth_id != booth_id
        or existing.campaign_id != campaign_id
        or existing.offline != item.offline
    )
    if not changed:
        return existing.id, False
    existing.state = state
    existing.frame_template_id = frame_id
    existing.activation_mode = activation
    existing.booth_id = booth_id
    existing.campaign_id = campaign_id
    existing.offline = item.offline
    db.flush()
    _write_synced_log(db, existing, device)
    return existing.id, True


def _write_synced_log(db: Session, session_obj: SessionModel, device: Device) -> None:
    db.add(
        SessionDeviceLog(
            session_id=session_obj.id,
            reason="synced",
            **_snapshot_payload(db, device, session_obj.frame_template_id),
        )
    )
    db.flush()


def _resolve_session_id(db: Session, device_id: str, session_ids: dict, session_local_id: str) -> str:
    if session_local_id in session_ids:
        return session_ids[session_local_id]
    row = db.query(SessionModel).filter(SessionModel.client_ref == session_local_id).first()
    if row is None:
        raise ValueError(f"session_local_id {session_local_id} not found")
    if row.device_id != device_id:
        raise ValueError(f"session_local_id {session_local_id} belongs to another device")
    return row.id


def _upsert_payment(
    db: Session, device: Device, session_ids: dict, item
) -> tuple[str, bool]:
    session_id = _resolve_session_id(db, device.id, session_ids, item.session_local_id)
    session_row = db.get(SessionModel, session_id)
    booth_id = _checked_ref(db, Booth, item.booth_id, "booth")
    if booth_id is None and session_row is not None:
        booth_id = session_row.booth_id
    campaign_id = _checked_ref(db, Campaign, item.campaign_id, "campaign")
    if campaign_id is None and session_row is not None:
        campaign_id = session_row.campaign_id
    voucher_id = _checked_ref(db, Voucher, item.voucher_id, "voucher")
    existing = (
        db.query(Payment).filter(Payment.client_ref == item.payment_local_id).first()
    )
    if existing is None:
        obj = Payment(
            client_ref=item.payment_local_id,
            device_id=device.id,
            session_id=session_id,
            booth_id=booth_id,
            campaign_id=campaign_id,
            voucher_id=voucher_id,
            amount=float(item.amount),
            currency=item.currency,
            method=item.method,
            status=item.status or "pending",
            provider=item.provider,
            provider_ref=item.provider_ref,
            gateway_payload=item.gateway_payload,
            paid_at=item.paid_at,
        )
        if item.created_at is not None:
            obj.created_at = item.created_at
        db.add(obj)
        db.flush()
        return obj.id, True
    if existing.device_id != device.id:
        raise ValueError(f"payment_local_id {item.payment_local_id} belongs to another device")
    existing.session_id = session_id
    existing.booth_id = booth_id
    existing.campaign_id = campaign_id
    existing.voucher_id = voucher_id
    existing.amount = float(item.amount)
    existing.currency = item.currency
    existing.method = item.method
    if item.status is not None:
        existing.status = item.status
    existing.provider = item.provider
    existing.provider_ref = item.provider_ref
    existing.gateway_payload = item.gateway_payload
    existing.paid_at = item.paid_at
    db.flush()
    return existing.id, True


def _redeem_voucher(
    db: Session, device: Device, session_ids: dict, item
) -> str:
    session_id = _resolve_session_id(db, device.id, session_ids, item.session_local_id)
    voucher = db.query(Voucher).filter(Voucher.code == item.code).first()
    if voucher is None:
        raise ValueError(f"voucher {item.code} not found")
    if voucher.device_id is not None and voucher.device_id != device.id:
        raise ValueError(f"voucher {item.code} belongs to another device")
    if voucher.status == "used" and voucher.session_id == session_id:
        return voucher.id  # idempotent retry
    now = wib_now()
    if voucher.status == "available" and voucher.expires_at is not None and voucher.expires_at <= now:
        raise ValueError(f"voucher {item.code} has expired")
    if voucher.status != "available":
        raise ValueError(f"voucher {item.code} is already used or voided")
    voucher.status = "used"
    voucher.session_id = session_id
    voucher.device_id = device.id
    voucher.used_at = now
    db.flush()
    return voucher.id


@router.post(
    "/bulk",
    response_model=BulkSyncResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Bulk push offline sqlite rows",
    description=(
        "Push kiosk offline data (sessions, payments, voucher redemptions) to the server in one call. "
        "Device is taken from the Bearer token. Records are processed sessions-first with per-record "
        "savepoints: one bad record fails alone while siblings still apply. Retries are idempotent via "
        "session_local_id/payment_local_id (sessions/payments) and voucher code. Writes one device_sync_logs row (trigger=kiosk)."
    ),
    responses={
        400: {"description": "Empty payload, over 200 items, or validation error"},
        401: {"description": "Missing device_id claim in the access token"},
        404: {"description": "Device not found"},
    },
)
def bulk_sync(payload: BulkSyncRequest, request: Request, db: Session = Depends(get_db)):
    device_id = require_request_device_id(request)
    device = db.get(Device, device_id)
    if device is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found.")

    total = len(payload.sessions) + len(payload.payments) + len(payload.voucher_redemptions)
    if total == 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Empty bulk payload.")
    if total > MAX_BULK_ITEMS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Too many items (max {MAX_BULK_ITEMS}). Split into smaller batches.",
        )

    log = DeviceSyncLog(device_id=device.id, trigger="kiosk", status="started", tables={})
    db.add(log)
    db.flush()

    tables: dict = {
        "session": {"pushed": 0, "failed": 0, "errors": []},
        "payment": {"pushed": 0, "failed": 0, "errors": []},
        "voucher": {"pushed": 0, "failed": 0, "errors": []},
    }
    results: dict[str, list] = {"sessions": [], "payments": [], "vouchers": []}
    session_ids: dict[str, str] = {}

    for item in payload.sessions:
        try:
            with db.begin_nested():
                sid, _ = _upsert_session(db, device, item)
                session_ids[item.session_local_id] = sid
            results["sessions"].append(BulkRecordResult(ref=item.session_local_id, id=sid))
            tables["session"]["pushed"] += 1
        except Exception as exc:
            msg = f"{item.session_local_id}: {exc}"
            results["sessions"].append(BulkRecordResult(ref=item.session_local_id, ok=False, error=str(exc)[:200]))
            _fail(tables, "session", msg)

    for item in payload.payments:
        try:
            with db.begin_nested():
                pid, _ = _upsert_payment(db, device, session_ids, item)
            results["payments"].append(BulkRecordResult(ref=item.payment_local_id, id=pid))
            tables["payment"]["pushed"] += 1
        except Exception as exc:
            msg = f"{item.payment_local_id}: {exc}"
            results["payments"].append(BulkRecordResult(ref=item.payment_local_id, ok=False, error=str(exc)[:200]))
            _fail(tables, "payment", msg)

    for item in payload.voucher_redemptions:
        try:
            with db.begin_nested():
                vid = _redeem_voucher(db, device, session_ids, item)
            results["vouchers"].append(BulkRecordResult(ref=item.code, id=vid))
            tables["voucher"]["pushed"] += 1
        except Exception as exc:
            msg = f"{item.code}: {exc}"
            results["vouchers"].append(BulkRecordResult(ref=item.code, ok=False, error=str(exc)[:200]))
            _fail(tables, "voucher", msg)

    failed = sum(t["failed"] for t in tables.values())
    pushed = sum(t["pushed"] for t in tables.values())
    if failed == 0:
        log.status = "success"
    elif pushed == 0:
        log.status = "failed"
    else:
        log.status = "partial"
    log.tables = tables
    log.meta = payload.meta
    if log.status != "success":
        parts = [f"{name} failed {t['failed']}" for name, t in tables.items() if t["failed"]]
        log.error = "; ".join(parts)[:500]
    log.finished_at = wib_now()
    db.commit()
    db.refresh(log)

    summary = {
        name: BulkSummary(
            ok=len([r for r in results[key] if r.ok]),
            failed=tables[name]["failed"],
        )
        for name, key in (("session", "sessions"), ("payment", "payments"), ("voucher", "vouchers"))
    }
    return BulkSyncResponse(results=results, summary=summary, sync_log_id=log.id)

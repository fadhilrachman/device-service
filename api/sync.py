from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import or_
from sqlalchemy.orm import Session

from api.config import _active_campaign, _device_vouchers, _resolve_frames
from api.session import _snapshot_payload
from api.voucher import _to_response as _voucher_response
from database import get_db
from lib.device_identity import require_request_device_id
from lib.time import wib_now
from lib.utils import new_session_code
from models.booth import Booth
from models.campaign import Campaign
from models.camera_profile import CameraProfile
from models.device import Device
from models.device_sync_log import DeviceSyncLog
from models.frame_template import FrameTemplate
from models.payment import Payment
from models.printer_profile import PrinterProfile
from models.session import ActivationMode, SessionModel, SessionState
from models.session_device_log import SessionDeviceLog
from models.voucher import Voucher
from schemas.config import CameraProfileResponse, FrameTemplateResponse, PrinterProfileResponse
from schemas.sync import (
    MAX_BULK_ITEMS,
    BulkChangesResponse,
    BulkRecordResult,
    BulkSummary,
    BulkSyncRequest,
    BulkSyncResponse,
    SyncConfigResponse,
    SyncDeviceResponse,
    SyncFrameTemplatesResponse,
)

router = APIRouter(prefix="/sync", tags=["sync"])

MAX_ERRORS_PER_TABLE = 10

# Pull side of the sync, returned with the push results.
MAX_PULL_VOUCHERS = 500
# How far back to look for the watermark of "what this device already got".
SYNC_LOG_LOOKBACK = 20
# meta key holding the frame ids delivered in a sync, used to compute "new".
FRAME_DELIVERY_META_KEY = "frame_templates_delivered"

# Columns the kiosk may self-report through BulkSyncRequest.device. Identity,
# binding and capabilities columns stay admin/SSO owned, so they are never
# written from here. camera_health/printer_health are ConnectionState enums and
# are unwrapped to their plain string value before hitting the Text columns.
DEVICE_SYNC_FIELDS = ("app_version", "storage_state", "camera_health", "printer_health")


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


def _allocate_session_code(db: Session, preferred: str | None = None) -> str:
    """Return a unique session code, preferring the kiosk-sent value when set.

    Retries a few times on collision before giving up (8 random chars give
    ~5e14 combinations, so a collision is effectively impossible).
    """
    candidates = ([preferred] if preferred else []) + [new_session_code() for _ in range(6)]
    for code in candidates:
        if not db.query(SessionModel.id).filter(SessionModel.code == code).first():
            return code
    raise ValueError("Unable to allocate a unique session code at this time.")


def _upsert_session(db: Session, device: Device, item) -> tuple[str, bool]:
    """Insert or refresh a session by session_local_id. Returns (id, changed)."""
    state = _parse_state(item.state)
    activation = _parse_activation(item.activation_mode)
    frame_id = _resolve_frame(db, item.frame_template_id)
    booth_id = _checked_ref(db, Booth, item.booth_id, "booth")
    campaign_id = _checked_ref(db, Campaign, item.campaign_id, "campaign")
    incoming_code = (getattr(item, "code", None) or "").strip() or None

    existing = (
        db.query(SessionModel).filter(SessionModel.client_ref == item.session_local_id).first()
    )
    if existing is None:
        obj = SessionModel(
            client_ref=item.session_local_id,
            code=_allocate_session_code(db, incoming_code),
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
    if existing.code is None:
        existing.code = _allocate_session_code(db, incoming_code)
        changed = True
    else:
        changed = False
    changed = (
        changed
        or existing.state != state
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


def _apply_device_update(db: Session, device: Device, item) -> bool:
    """Apply the optional `device` block of a bulk push onto the caller's row.

    Health fields keep the semantics of PATCH /devices/heartbeat: only what the
    kiosk sent is overwritten (camera/printer accept only the ConnectionState
    values "connect"/"disconnect", enforced by the schema). Liveness stamps
    (last_seen_at, last_heartbeat, connectivity) stay server-owned and are set
    to server time, so a kiosk cannot backdate them. `updated_at` is
    deliberately not touched: it flags config changes for the admin has_update
    check, and a sync is not a config change (see models/device.py).
    """
    now = wib_now()
    device.last_seen_at = now
    device.last_heartbeat = now
    device.connectivity = "online"
    changed = False
    for field in DEVICE_SYNC_FIELDS:
        value = getattr(item, field)
        if value is None:
            continue
        value = getattr(value, "value", value)  # enum -> plain str for the Text column
        if getattr(device, field) != value:
            setattr(device, field, value)
            changed = True
    db.flush()
    return changed


def _delivered_frame_ids(db: Session, device_id: str) -> set[str]:
    """Frame ids this device already received, from its newest sync log.

    `campaign_frame_templates` has no timestamps (only the two FK columns), so
    "newly assigned to my campaign" cannot be derived from the link table. The
    last delivery watermark is written into `device_sync_logs.meta` instead.
    """
    logs = (
        db.query(DeviceSyncLog)
        .filter(DeviceSyncLog.device_id == device_id)
        .order_by(DeviceSyncLog.started_at.desc())
        .limit(SYNC_LOG_LOOKBACK)
        .all()
    )
    for log in logs:
        meta = log.meta or {}
        delivered = meta.get(FRAME_DELIVERY_META_KEY)
        if isinstance(delivered, list):
            return {str(frame_id) for frame_id in delivered}
    return set()


def _changed_vouchers(
    db: Session, device: Device, campaign: Campaign | None, since
) -> list[Voucher]:
    """This device's vouchers touched after `since` (all of them when NULL)."""
    if campaign is None:
        return []
    query = _device_vouchers(db, device.id, campaign)
    if since is not None:
        query = query.filter(
            or_(Voucher.created_at > since, Voucher.updated_at > since)
        )
    return (
        query.order_by(Voucher.created_at.desc(), Voucher.id.desc())
        .limit(MAX_PULL_VOUCHERS)
        .all()
    )


def _pull_changes(db: Session, device: Device, campaign: Campaign | None) -> BulkChangesResponse:
    """Build the server -> kiosk half of the sync response."""
    since = device.last_synced_at
    vouchers = _changed_vouchers(db, device, campaign, since)

    frames = _resolve_frames(db, campaign)
    delivered = _delivered_frame_ids(db, device.id)
    new_frames = [frame for frame in frames if frame.id not in delivered]

    camera = (
        db.get(CameraProfile, device.camera_profile_id)
        if device.camera_profile_id
        else None
    )
    printer = (
        db.get(PrinterProfile, device.printer_profile_id)
        if device.printer_profile_id
        else None
    )
    offline_vouchers = 0
    if campaign:
        # Same count as GET /config: available vouchers of the active campaign.
        offline_vouchers = (
            _device_vouchers(db, device.id, campaign)
            .filter(Voucher.status == "available")
            .count()
        )

    return BulkChangesResponse(
        # Same shape as GET /vouchers, so the kiosk merges both identically.
        vouchers=[_voucher_response(db, voucher) for voucher in vouchers],
        config=SyncConfigResponse(
            device=SyncDeviceResponse.model_validate(device),
            camera_profile=CameraProfileResponse.model_validate(camera) if camera else None,
            printer_profile=PrinterProfileResponse.model_validate(printer) if printer else None,
            offline_vouchers=offline_vouchers,
        ),
        frame_templates=SyncFrameTemplatesResponse(
            campaign_id=campaign.id if campaign else None,
            campaign_frames=[FrameTemplateResponse.model_validate(frame) for frame in frames],
            new_frames=[FrameTemplateResponse.model_validate(frame) for frame in new_frames],
        ),
        voucher_since=since,
    )


@router.post(
    "/bulk",
    response_model=BulkSyncResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Bulk push offline sqlite rows",
    description=(
        "Push kiosk offline data (sessions, payments, voucher redemptions) to the server in one call. "
        "Device is taken from the Bearer token. Records are processed sessions-first with per-record "
        "savepoints: one bad record fails alone while siblings still apply. Retries are idempotent via "
        "session_local_id/payment_local_id (sessions/payments) and voucher code. Writes one device_sync_logs row (trigger=kiosk). "
        "An optional `device` block reports the kiosk's own state (app_version, storage_state, "
        "camera_health, printer_health) and is applied to the caller's row; camera_health/printer_health "
        "accept only connect|disconnect. It also stamps last_seen_at/last_heartbeat like a heartbeat, and "
        "makes a device-only push (no records) a valid request. "
        "The response always carries a `changes` block with the server -> kiosk half: vouchers changed "
        "since devices.last_synced_at, the GET /config bundle (without device storage_state/camera_health/"
        "printer_health), and frame templates (full campaign set plus the newly assigned subset). "
        "This sync then stamps devices.last_synced_at, which the next sync diffs against."
    ),
    responses={
        400: {"description": "Empty payload (no records and no device fields), over 200 items, or validation error"},
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
    # A batch may carry only a device self-report (nothing to flush offline).
    device_payload = payload.device
    has_device_update = device_payload is not None and any(
        getattr(device_payload, field) is not None for field in DEVICE_SYNC_FIELDS
    )
    if total == 0 and not has_device_update:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Empty bulk payload.")
    if total > MAX_BULK_ITEMS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Too many items (max {MAX_BULK_ITEMS}). Split into smaller batches.",
        )

    device_updated: bool | None = None
    if has_device_update:
        device_updated = _apply_device_update(db, device, device_payload)

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

    # Pull side: everything the device missed while it was offline. Built before
    # last_synced_at is stamped so the voucher filter uses the previous watermark.
    campaign = _active_campaign(db, device.id)
    changes = _pull_changes(db, device, campaign)
    device.last_synced_at = wib_now()
    changes.synced_at = device.last_synced_at
    # Re-snapshot the device block so the response carries the new watermark
    # (the pull above froze the pre-stamp value).
    changes.config.device = SyncDeviceResponse.model_validate(device)

    failed = sum(t["failed"] for t in tables.values())
    pushed = sum(t["pushed"] for t in tables.values())
    if failed == 0:
        log.status = "success"
    elif pushed == 0:
        log.status = "failed"
    else:
        log.status = "partial"
    log.tables = tables
    meta = dict(payload.meta or {})
    if device_payload is not None:
        # Keep what the kiosk said about itself on the audit row, under its own
        # key so it never collides with the caller-provided meta. mode="json"
        # unwraps the ConnectionState enums to their plain values for the JSON column.
        meta["device"] = device_payload.model_dump(exclude_none=True, mode="json")
    # Delivery watermark for the next sync's "newly assigned frames" diff.
    meta[FRAME_DELIVERY_META_KEY] = [frame.id for frame in changes.frame_templates.campaign_frames]
    meta["pull"] = {
        "vouchers": len(changes.vouchers),
        "frames_total": len(changes.frame_templates.campaign_frames),
        "frames_new": len(changes.frame_templates.new_frames),
        "campaign_id": changes.frame_templates.campaign_id,
        "voucher_since": changes.voucher_since.isoformat() if changes.voucher_since else None,
    }
    log.meta = meta
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
    return BulkSyncResponse(
        results=results,
        summary=summary,
        sync_log_id=log.id,
        device_updated=device_updated,
        changes=changes,
    )

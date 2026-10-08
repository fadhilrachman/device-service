from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from schemas.config import CameraProfileResponse, FrameTemplateResponse, PrinterProfileResponse
from schemas.device import DeviceAssignmentResponse
from schemas.voucher import VoucherResponse

MAX_BULK_ITEMS = 200
# devices.app_version is String(50); enforcing it here turns an oversized value
# into a 422 naming the field instead of a Postgres 22001 truncation error.
APP_VERSION_MAX = 50


class BulkSessionItem(BaseModel):
    """One offline kiosk session. Idempotency key is ``session_local_id``."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "session_local_id": "ses_m7a1b2c3d_x4y9z1",
                "state": "complete",
                "activation_mode": "qr",
                "frame_template_id": "7c9e0a2b-1f3d-4a5b-8c6d-9e0f1a2b3c4d",
                "booth_id": "b1c2d3e4-f5a6-47b8-89c0-d1e2f3a4b5c6",
                "campaign_id": "c1d2e3f4-a5b6-47c8-89d0-e1f2a3b4c5d6",
                "config_snapshot_id": None,
                "offline": True,
                "created_at": "2026-09-30T10:00:01",
            }
        }
    )

    session_local_id: str = Field(description="Kiosk sessions.local_id (e.g. ses_xxx). Used for idempotent upsert; never reused across kiosks.")
    code: Optional[str] = Field(default=None, description="Optional kiosk-provided session code (SES-XXXXXXXX). Ignored when empty; the server generates one when missing.")
    state: str = Field(description="Final kiosk state. Must be a server SessionState: started, payment_choice, simulation, take_photo, re_take, print, complete, cancelled.")
    frame_template_id: Optional[str] = Field(default=None, description="Server frame UUID, or a frm_-prefixed kiosk-local id (stored as null). Unknown server ids fail this record.")
    activation_mode: Optional[str] = Field(default=None, description="qr or voucher.")
    booth_id: Optional[str] = Field(default=None, description="Must exist when sent; no window check (offline backlog accepted).")
    campaign_id: Optional[str] = Field(default=None, description="Must exist when sent; no window check.")
    config_snapshot_id: Optional[str] = Field(default=None, description="Passthrough, stored as-is.")
    offline: bool = Field(default=False, description="True when the session was created offline.")
    created_at: Optional[datetime] = Field(default=None, description="Kiosk creation time (offline truth). Defaults to server time.")


class BulkPaymentItem(BaseModel):
    """One offline kiosk payment. Linked to a session via ``session_local_id``."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "payment_local_id": "pay_m7a1b2c3d_q8w2e4",
                "session_local_id": "ses_m7a1b2c3d_x4y9z1",
                "amount": 50000,
                "currency": "IDR",
                "method": "qris",
                "status": "paid",
                "provider": "xendit",
                "provider_ref": "inv_abc123",
                "created_at": "2026-09-30T10:01:12",
            }
        }
    )

    payment_local_id: str = Field(description="Kiosk payments.local_id. Used for idempotent upsert.")
    session_local_id: str = Field(description="session_local_id of the session in this batch or a previously synced one.")
    amount: float = Field(description="Required. Stored as Numeric(12,2).")
    currency: str = Field(default="IDR", description="ISO currency code.")
    method: Optional[str] = Field(default=None, description="Free string, e.g. qris, voucher.")
    status: Optional[str] = Field(default=None, description="Kiosk word, canonicalized on ingest (paid->succeeded, cancelled->failed). Defaults to pending.")
    provider: Optional[str] = Field(default=None, description="Passthrough, e.g. xendit, stub.")
    provider_ref: Optional[str] = Field(default=None, description="Provider reference. Must be globally unique when sent.")
    gateway_payload: Optional[dict] = Field(default=None, description="Raw gateway payload passthrough from kiosk.")
    paid_at: Optional[datetime] = Field(default=None, description="Kiosk-recorded payment time.")
    booth_id: Optional[str] = Field(default=None, description="Explicit booth; must exist. Defaults to the session's booth.")
    campaign_id: Optional[str] = Field(default=None, description="Explicit campaign; must exist. Defaults to the session's campaign.")
    voucher_id: Optional[str] = Field(default=None, description="Linked voucher server id; must exist when sent.")
    created_at: Optional[datetime] = Field(default=None, description="Kiosk creation time. Defaults to server time.")


class BulkVoucherItem(BaseModel):
    """Redeem a server voucher for an offline session (by natural key ``code``)."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {"code": "LEB-001", "session_local_id": "ses_m7a1b2c3d_x4y9z1"}
        }
    )

    code: str = Field(description="Existing server voucher code. Must be available (or already used by the same session for idempotent retry).")
    session_local_id: str = Field(description="session_local_id of the session in this batch or a previously synced one.")


class ConnectionState(str, Enum):
    """Peripheral link state a kiosk may report for camera/printer.

    Deliberately only two values: "is it plugged in right now". Anything else
    (including the free text PATCH /devices/heartbeat still accepts) is a 422
    on this endpoint so admin dashboards get one predictable vocabulary.
    """

    CONNECT = "connect"
    DISCONNECT = "disconnect"


class BulkDeviceItem(BaseModel):
    """Optional device self-report sent along with a bulk batch.

    Only kiosk-owned fields are exposed here. Identity and binding fields
    (``device_code``, ``device_code_sso``, ``tenant_id``, ``status``,
    ``camera_profile_id``, ``printer_profile_id``) stay server-managed, and so
    does ``capabilities`` (admin/SSO owned). Unknown keys are rejected
    (``extra="forbid"``), so a typo like ``storageStatus`` fails loudly instead
    of silently doing nothing.
    """

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "app_version": "1.4.0",
                "storage_state": "free 12.4GB",
                "camera_health": "connect",
                "printer_health": "disconnect",
            }
        },
    )

    app_version: Optional[str] = Field(default=None, max_length=APP_VERSION_MAX, description="Kiosk app version. Must fit devices.app_version (50 chars) or the request is 422.")
    storage_state: Optional[str] = Field(default=None, description="Free text storage status. Same column as PATCH /devices/heartbeat.")
    camera_health: Optional[ConnectionState] = Field(default=None, description="Camera link state: connect or disconnect.")
    printer_health: Optional[ConnectionState] = Field(default=None, description="Printer link state: connect or disconnect.")


class BulkSyncRequest(BaseModel):
    """Push offline sqlite rows to the server. Processed sessions -> payments -> vouchers."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "sessions": [
                    {
                        "session_local_id": "ses_m7a1b2c3d_x4y9z1",
                        "state": "complete",
                        "activation_mode": "qr",
                        "frame_template_id": "7c9e0a2b-1f3d-4a5b-8c6d-9e0f1a2b3c4d",
                        "booth_id": "b1c2d3e4-f5a6-47b8-89c0-d1e2f3a4b5c6",
                        "campaign_id": "c1d2e3f4-a5b6-47c8-89d0-e1f2a3b4c5d6",
                        "offline": True,
                        "created_at": "2026-09-30T10:00:01",
                    }
                ],
                "payments": [
                    {
                        "payment_local_id": "pay_m7a1b2c3d_q8w2e4",
                        "session_local_id": "ses_m7a1b2c3d_x4y9z1",
                        "amount": 50000,
                        "currency": "IDR",
                        "method": "qris",
                        "status": "paid",
                        "provider": "xendit",
                        "provider_ref": "inv_abc123",
                        "gateway_payload": {"invoice_id": "inv_abc123"},
                        "paid_at": "2026-09-30T10:01:12",
                        "created_at": "2026-09-30T10:01:12",
                    }
                ],
                "voucher_redemptions": [{"code": "LEB-001", "session_local_id": "ses_m7a1b2c3d_x4y9z1"}],
                "device": {
                    "app_version": "1.4.0",
                    "storage_state": "free 12.4GB",
                    "camera_health": "connect",
                    "printer_health": "disconnect",
                },
                "meta": {"app_version": "1.4.0"},
            }
        }
    )

    sessions: list[BulkSessionItem] = Field(default_factory=list, description="Offline sessions to upsert (max 200 items total per request).")
    payments: list[BulkPaymentItem] = Field(default_factory=list, description="Offline payments; session_local_id must resolve to a session in this batch or an earlier one.")
    voucher_redemptions: list[BulkVoucherItem] = Field(default_factory=list, description="Voucher redemptions against existing server voucher codes.")
    device: Optional[BulkDeviceItem] = Field(default=None, description="Optional device self-report applied to the caller's row (the device comes from the Bearer token). At least one field must be set, otherwise an empty request is still rejected with 400.")
    meta: Optional[dict] = Field(default=None, description="Optional kiosk info (e.g. app_version), stored on the sync log row.")


class SyncDeviceResponse(BaseModel):
    """`GET /config`'s device object minus liveness + health columns.

    ``last_seen_at`` / ``last_heartbeat`` are server-side liveness stamps the
    kiosk never needs (``connectivity`` + ``last_synced_at`` carry the state
    the kiosk actually uses). ``storage_state`` / ``camera_health`` /
    ``printer_health`` are dropped on purpose: the kiosk *pushes* them in
    BulkDeviceItem, so echoing them back in a pull payload would only invite
    the client to trust stale server state.
    """

    model_config = ConfigDict(from_attributes=True)

    id: str
    device_code: str
    tenant_id: Optional[str] = None
    name: Optional[str] = None
    serial_number: Optional[str] = None
    status: str
    is_verified: bool = False
    capabilities: object = None
    camera_profile_id: Optional[str] = None
    printer_profile_id: Optional[str] = None
    app_version: Optional[str] = None
    last_synced_at: object = None
    connectivity: Optional[str] = None
    device_assignment: Optional[DeviceAssignmentResponse] = None


class SyncConfigResponse(BaseModel):
    """Same bundle as GET /config, minus frames and device health fields.

    Frames live only in ``BulkChangesResponse.frame_templates`` as a flat list.
    """

    device: Optional[SyncDeviceResponse] = None
    camera_profile: Optional[CameraProfileResponse] = None
    printer_profile: Optional[PrinterProfileResponse] = None
    offline_vouchers: int = 0


class BulkChangesResponse(BaseModel):
    """Server -> kiosk half of the sync, returned next to the push results.

    Lets one call do both directions: the kiosk pushes offline rows and gets the
    data it missed while it was offline.
    """

    vouchers: list[VoucherResponse] = Field(default_factory=list, description="This device's vouchers (active campaign) whose created_at or updated_at is newer than devices.last_synced_at. On the first sync (NULL watermark) every voucher is returned.")
    config: SyncConfigResponse = Field(default_factory=SyncConfigResponse)
    frame_templates: list[FrameTemplateResponse] = Field(default_factory=list, description="Full frame set resolved for this device: campaign-linked public frames, or every public frame when the campaign links none (same rule as GET /config.frames).")
    voucher_since: Optional[datetime] = Field(default=None, description="Watermark used to select vouchers (null on the first sync).")
    synced_at: Optional[datetime] = Field(default=None, description="devices.last_synced_at written at the end of this sync; the next sync diffs against it.")


class BulkRecordResult(BaseModel):
    ref: str = Field(description="Echo of session_local_id / payment_local_id (sessions/payments) or code (vouchers).")
    id: Optional[str] = Field(default=None, description="Server row id when ok.")
    ok: bool = Field(default=True, description="False when this record failed; siblings still processed.")
    error: Optional[str] = Field(default=None, description="Per-record failure reason; null on success.")


class BulkSummary(BaseModel):
    ok: int = 0
    failed: int = 0


class BulkSyncResponse(BaseModel):
    results: dict[str, list[BulkRecordResult]] = Field(description="Per-record outcomes keyed by sessions, payments, vouchers.")
    summary: dict[str, BulkSummary] = Field(description="ok/failed counts per table.")
    sync_log_id: str = Field(description="device_sync_logs row id for this action (admin audit).")
    device_updated: Optional[bool] = Field(default=None, description="null when no `device` block was sent, else true when the device row actually changed.")
    changes: Optional[BulkChangesResponse] = Field(default=None, description="Server -> kiosk payload: vouchers changed since last_synced_at, the GET /config bundle (minus device health fields and frames), and frame templates (full set).")

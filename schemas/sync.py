from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

MAX_BULK_ITEMS = 200


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
    status: Optional[str] = Field(default=None, description="Free string as recorded by kiosk, e.g. paid, cancelled. Defaults to pending.")
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
                "meta": {"app_version": "1.4.0"},
            }
        }
    )

    sessions: list[BulkSessionItem] = Field(default_factory=list, description="Offline sessions to upsert (max 200 items total per request).")
    payments: list[BulkPaymentItem] = Field(default_factory=list, description="Offline payments; session_local_id must resolve to a session in this batch or an earlier one.")
    voucher_redemptions: list[BulkVoucherItem] = Field(default_factory=list, description="Voucher redemptions against existing server voucher codes.")
    meta: Optional[dict] = Field(default=None, description="Optional kiosk info (e.g. app_version), stored on the sync log row.")


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

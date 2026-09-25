"""Conflict resolution rules for the bidirectional sync between SQLite and PostgreSQL."""


def voucher_status_wins(local_status: str | None, remote_status: str | None) -> str:
    """
    Decide which side's voucher status should be kept.

    Rules:
    - If the local voucher was redeemed ('used') on this device while the server
      still reports it available/expired/voided, the local redemption wins (it will
      be pushed on a subsequent sync).
    - If the server already marked it 'used', the server wins (it was redeemed
      elsewhere; adopting it prevents double-use).
    - Otherwise the server value wins.
    """
    if local_status == "used" and remote_status != "used":
        return "local"
    return "remote"


def device_fields_for_push(column_name: str) -> bool:
    """True when a Device column is owned by the device itself (pushed, not overwritten)."""
    return column_name in {
        "tenant_id",
        "last_seen_at",
        "last_heartbeat",
        "connectivity",
        "storage_state",
        "camera_health",
        "printer_health",
    }
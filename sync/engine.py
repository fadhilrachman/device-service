import logging
import threading
from datetime import datetime

from sqlalchemy import delete, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import SQLAlchemyError

import models  # noqa: F401  (register all tables on Base.metadata)
from config import APP_VERSION, DEVICE_CODE, DEVICE_NAME, resolve_device_id
from database import Base, local_engine, local_session, remote_session
from lib.time import wib_now
from models.device import Device
from models.payment import Payment
from models.session import SessionModel
from models.session_device_log import SessionDeviceLog
from models.sync import SyncMarker, SyncOutbox
from models.voucher import Voucher
from sync.conflict import device_fields_for_push, voucher_status_wins

logger = logging.getLogger("sync")

# Order in which config tables are pulled from the server (parents first).
PULL_ORDER = [
    "campaigns",
    "booths",
    "camera_profiles",
    "printer_profiles",
    "frame_templates",
    "voucher_batches",
    "campaign_frame_templates",
    "devices",
    "device_assignments",
    "vouchers",
]

# Order in which operational rows are pushed to the server (parents first).
PUSH_ORDER = ["sessions", "session_device_logs", "payments", "vouchers"]

MODEL_BY_TABLE = {
    "sessions": SessionModel,
    "session_device_logs": SessionDeviceLog,
    "payments": Payment,
    "vouchers": Voucher,
}

# Operational tables referencing config tables (used to keep SQLite FK integrity
# when a config row is removed server-side: matching the DB's ON DELETE SET NULL).
FK_REFS = {
    "campaigns": [("sessions", "campaign_id"), ("payments", "campaign_id")],
    "booths": [("sessions", "booth_id"), ("payments", "booth_id")],
    "camera_profiles": [("session_device_logs", "camera_profile_id")],
    "printer_profiles": [("session_device_logs", "printer_profile_id")],
    "frame_templates": [
        ("sessions", "frame_template_id"),
        ("session_device_logs", "frame_template_id"),
    ],
    "vouchers": [("payments", "voucher_id")],
    "devices": [
        ("sessions", "device_id"),
        ("payments", "device_id"),
        ("vouchers", "device_id"),
        ("session_device_logs", "device_id"),
    ],
}

# Fields on the Device row owned by the device itself (heartbeat / health).
DEVICE_PUSH_FIELDS = {
    "tenant_id",
    "last_seen_at",
    "last_heartbeat",
    "connectivity",
    "storage_state",
    "camera_health",
    "printer_health",
}


class SyncEngine:
    def __init__(self) -> None:
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._run_lock = threading.Lock()
        self.online: bool | None = None
        self._online_checked_at: datetime | None = None
        self.last_sync_at: datetime | None = None
        self.last_result: dict | None = None
        self.last_error: str | None = None

    # ------------------------------------------------------------------ thread

    def start(self, interval: int) -> None:
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, args=(interval,), daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self, interval: int) -> None:
        while not self._stop.is_set():
            try:
                self.last_result = self.run_once()
                self.last_error = None
            except Exception as exc:  # noqa: BLE001
                self.last_error = str(exc)
                self.last_result = {"ok": False, "error": str(exc)}
                logger.exception("sync cycle failed")
            self._stop.wait(interval)

    # -------------------------------------------------------- online detection

    def is_online(self, force: bool = False) -> bool:
        now = wib_now()
        if self.online is not None and self._online_checked_at and not force:
            if (now - self._online_checked_at).total_seconds() < 10:
                return self.online
        try:
            with remote_session() as s:
                s.execute(text("SELECT 1"))
            self.online = True
        except SQLAlchemyError:
            self.online = False
        self._online_checked_at = now
        return self.online

    # -------------------------------------------------------------------- run

    def run_once(self) -> dict:
        with self._run_lock:
            if not self.is_online(force=True):
                self.online = False
                return {"ok": False, "error": "offline"}

            self.online = True
            with local_session() as local, remote_session() as remote:
                self.ensure_local_device(local)
                local.commit()

                self.push_device(local, remote)
                self.push_outbox(local, remote)
                self.pull_config(local, remote)
                self.pull_payments(local, remote)

                now = wib_now()
                self._write_marker(local, "last_sync", now)
                local.commit()

            self.last_sync_at = wib_now()
            return {"ok": True, "at": self.last_sync_at, "pending": self.outbox_counts()[0]}

    # ------------------------------------------------------------- local init

    def ensure_local_device(self, db) -> Device:
        device_id = resolve_device_id()
        dev = db.get(Device, device_id)
        if dev is None:
            code = DEVICE_CODE or f"DEV-{device_id[:8].upper()}"
            dev = Device(
                id=device_id,
                device_code=code,
                name=DEVICE_NAME or None,
                app_version=APP_VERSION,
                status="active",
            )
            db.add(dev)
        return dev

    # ----------------------------------------------------------------- push

    def push_device(self, local, remote) -> None:
        device_id = resolve_device_id()
        dev = local.get(Device, device_id)
        if dev is None:
            return
        table = Device.__table__
        data = self._orm_row_to_dict(dev)
        # The device only reports its identity + tenant binding + health. Everything
        # else (camera_profile_id, printer_profile_id, name, status, ...) belongs to
        # the admin panel and must never be overwritten from a device.
        push_cols = {"id", "device_code", "app_version"}.union(DEVICE_PUSH_FIELDS)
        subset = {k: v for k, v in data.items() if k in push_cols}
        # A local NULL means "unknown", never "delete the server value": without
        # this, a device that authorized straight to Neon (SQLite still NULL)
        # would wipe the Neon values on the next sync.
        updatable = {k: v for k, v in subset.items() if k != "id" and v is not None}
        stmt = pg_insert(table).values(**subset)
        if not updatable:
            stmt = stmt.on_conflict_do_nothing(index_elements=[table.c.id])
        else:
            stmt = stmt.on_conflict_do_update(
                index_elements=[table.c.id],
                set_={k: getattr(stmt.excluded, k) for k in updatable},
            )
        remote.execute(stmt)
        remote.commit()

    def push_outbox(self, local, remote) -> None:
        pending = (
            local.query(SyncOutbox)
            .filter(SyncOutbox.synced_at.is_(None))
            .order_by(SyncOutbox.created_at.asc())
            .all()
        )
        for entry in pending:
            try:
                if entry.op == "delete":
                    self._push_delete(entry, remote)
                else:
                    self._push_row(entry, local, remote)
                remote.commit()
            except SQLAlchemyError:
                remote.rollback()
                raise
            entry.synced_at = wib_now()
            local.commit()

    def _push_row(self, entry: SyncOutbox, local, remote) -> None:
        model = MODEL_BY_TABLE.get(entry.table_name)
        if model is None:
            return
        row = local.get(model, entry.row_id)
        if row is None:
            return
        table = model.__table__
        data = self._orm_row_to_dict(row)
        stmt = pg_insert(table).values(**data)
        if entry.table_name == "payments":
            # Payments are INSERT-only: payment status is owned by the server
            # after creation (webhook); never overwrite a newer server state.
            stmt = stmt.on_conflict_do_nothing(index_elements=[table.c.id])
        else:
            stmt = stmt.on_conflict_do_update(
                index_elements=[table.c.id],
                set_={
                    c.name: getattr(stmt.excluded, c.name)
                    for c in table.columns
                    if c.name != "id"
                },
            )
        remote.execute(stmt)

    def _push_delete(self, entry: SyncOutbox, remote) -> None:
        model = MODEL_BY_TABLE.get(entry.table_name)
        if model is None:
            return
        table = model.__table__
        remote.execute(delete(table).where(table.c.id == entry.row_id))

    # ----------------------------------------------------------------- pull

    def pull_config(self, local, remote) -> None:
        device_id = resolve_device_id()
        remote_rows = self._fetch_remote_config(remote, device_id)

        conn = local_engine.connect().execution_options(isolation_level="AUTOCOMMIT")
        try:
            conn.execute(text("PRAGMA foreign_keys=OFF"))
            self._apply_config_pull(conn, remote_rows)
            conn.execute(text("PRAGMA foreign_keys=ON"))
        finally:
            conn.close()

    def _fetch_remote_config(self, remote, device_id: str) -> dict[str, list[dict]]:
        result: dict[str, list[dict]] = {}
        for name in PULL_ORDER:
            table = Base.metadata.tables[name]
            if name == "devices":
                rows = (
                    remote.execute(select(table).where(table.c.id == device_id))
                    .mappings()
                    .all()
                )
            elif name == "device_assignments":
                rows = (
                    remote.execute(
                        select(table).where(table.c.device_id == device_id)
                    )
                    .mappings()
                    .all()
                )
            else:
                rows = remote.execute(select(table)).mappings().all()
            result[name] = [dict(r) for r in rows]
        return result

    def _apply_config_pull(self, conn, remote_rows: dict[str, list[dict]]) -> None:
        for name in PULL_ORDER:
            table = Base.metadata.tables[name]
            rows = remote_rows.get(name, [])

            if name == "campaign_frame_templates":
                # M2M junction table: composite PK, no single 'id' column.
                # Full replace is safe here (nothing references it).
                conn.execute(delete(table))
                for row in rows:
                    conn.execute(sqlite_insert(table).values(**row))
                continue

            present = {r["id"] for r in rows}

            if name == "vouchers":
                self._merge_vouchers(conn, rows)
            elif name == "devices":
                self._upsert_rows(conn, table, rows, preserve=DEVICE_PUSH_FIELDS)
            else:
                self._upsert_rows(conn, table, rows, preserve=set())

            if name == "devices":
                # Keep the local placeholder if the server has no row for us yet.
                continue
            self._null_fk_refs(conn, name, present)
            self._delete_missing(conn, table, present)

    def _merge_vouchers(self, conn, rows: list[dict]) -> None:
        table = Base.metadata.tables["vouchers"]
        for row in rows:
            local_status = conn.execute(
                select(table.c.status).where(table.c.id == row["id"])
            ).scalar()
            winner = voucher_status_wins(local_status, row.get("status"))
            if winner == "local":
                continue
            self._upsert_rows(conn, table, [row], preserve=set())

    def _upsert_rows(self, conn, table, rows: list[dict], preserve: set[str]) -> None:
        for row in rows:
            conflict_cols = [c.name for c in table.primary_key]
            update_cols = [
                k
                for k, v in row.items()
                if k not in conflict_cols
                and k not in preserve
                and v is not None
            ]
            stmt = sqlite_insert(table).values(**row)
            if not update_cols:
                stmt = stmt.on_conflict_do_nothing(index_elements=conflict_cols)
            else:
                stmt = stmt.on_conflict_do_update(
                    index_elements=conflict_cols,
                    set_={k: sqlite_insert(table).excluded[k] for k in update_cols},
                )
            conn.execute(stmt)

    def _null_fk_refs(self, conn, config_table: str, present: set[str]) -> None:
        for dep_table, fk_col in FK_REFS.get(config_table, []):
            dep = Base.metadata.tables[dep_table]
            if not present:
                stmt = update(dep).where(dep.c[fk_col].is_not(None)).values({fk_col: None})
            else:
                stmt = (
                    update(dep)
                    .where(dep.c[fk_col].not_in(present))
                    .values({fk_col: None})
                )
            conn.execute(stmt)

    def _delete_missing(self, conn, table, present: set[str]) -> None:
        if not present:
            conn.execute(delete(table))
            return
        conn.execute(delete(table).where(table.c.id.not_in(present)))

    def pull_payments(self, local, remote) -> None:
        device_id = resolve_device_id()
        table = Payment.__table__
        remote_rows = (
            remote.execute(select(table).where(table.c.device_id == device_id))
            .mappings()
            .all()
        )
        if not remote_rows:
            return

        # Only these fields can change server-side (webhook status transitions).
        server_fields = {
            "status",
            "paid_at",
            "provider",
            "provider_ref",
            "gateway_payload",
            "updated_at",
        }

        conn = local_engine.connect().execution_options(isolation_level="AUTOCOMMIT")
        try:
            conn.execute(text("PRAGMA foreign_keys=OFF"))
            for result in remote_rows:
                cols = dict(result)
                local_status = conn.execute(
                    select(table.c.status).where(table.c.id == cols["id"])
                ).scalar()
                if local_status is None:
                    self._upsert_rows(conn, table, [cols], preserve=set())
                    continue
                merge = {k: cols[k] for k in server_fields if k in cols}
                if merge:
                    # Plain UPDATE is safe here: reconcile applies only to rows we
                    # already have locally. (A partial upsert could make SQLAlchemy
                    # auto-append defaulted columns and attempt a broken INSERT.)
                    conn.execute(
                        update(table).where(table.c.id == cols["id"]).values(**merge)
                    )
            conn.execute(text("PRAGMA foreign_keys=ON"))
        finally:
            conn.close()

    # -------------------------------------------------------------- markers

    def _write_marker(self, db, name: str, value: datetime) -> None:
        marker = db.get(SyncMarker, name)
        if marker is None:
            db.add(SyncMarker(table_name=name, last_synced_at=value))
        else:
            marker.last_synced_at = value
            marker.last_error = None

    # --------------------------------------------------------------- counts

    def outbox_counts(self) -> tuple[int, int]:
        with local_session() as s:
            pending = (
                s.query(SyncOutbox).filter(SyncOutbox.synced_at.is_(None)).count()
            )
            total = s.query(SyncOutbox).count()
        return pending, total

    # -------------------------------------------------------------- helpers

    def _orm_row_to_dict(self, row) -> dict:
        table = row.__table__
        return {c.name: getattr(row, c.key) for c in table.columns}
# Our Lil Photobooth — Device Service

Service utama yang berjalan di setiap device photobooth (Raspberry Pi / SBC).
Menjalankan product (session, voucher, payment) secara **offline-first** dengan
SQLite lokal, lalu melakukan **periodic sync** ke PostgreSQL yang sama dengan
admin panel (backend2).

```
┌───────────────────────────────────────────────┐
│                Raspberry Pi                    │
│   FastAPI (device-service)  ──►  SQLite        │
│        │                                       │
│        └── periodic sync (30s)                 │
└────────────────────────────────────────────────┘
                    │
                    ▼
      PostgreSQL (Neon) — DB yang sama dgn admin
```

## Arsitektur

- **SQLite (`device.db`)** — database utama device. Semua operasi baca/tulis
  dilakukan di sini (offline-first). Schema identik dengan admin panel.
- **PostgreSQL (REMOTE_DATABASE_URL)** — database bersama. Sync engine:
  - **Push (device → server):** sessions, session_device_logs, payments,
    voucher redemption, heartbeat device.
  - **Pull (server → device):** campaigns, booths, camera/printer profiles,
    frame templates, voucher batches/vouchers, device assignments, device config.
- **Outbox pattern:** setiap perubahan lokal dicatat di tabel `sync_outbox`;
  sync engine memprosesnya secara idempotent saat online.
- **Conflict resolution:** config = server menang; data operasional = device
  menang; voucher di-redemption local = local menang sampai ter-push.

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env   # lalu isi REMOTE_DATABASE_URL & DEVICE_CODE
uvicorn main:app --host 0.0.0.0 --port 8000
```

## Environment

| Variable | Default | Keterangan |
|----------|---------|------------|
| `DEVICE_ID` | *(auto-generated)* | UUID device, harus match device di admin panel. Tersimpan permanen di `device.id` |
| `DEVICE_CODE` | `DEV-XXXXXXXX` | Kode device (harus match admin panel) |
| `DEVICE_NAME` | — | Nama device |
| `REMOTE_DATABASE_URL` | — | PostgreSQL URL (DB yang sama dengan admin panel) |
| `LOCAL_DB_PATH` | `device.db` | Path file SQLite lokal |
| `SYNC_INTERVAL_SECONDS` | `30` | Interval sync |
| `SYNC_ON_STARTUP` | `true` | Jalankan sync saat service start |
| `PAYMENT_PROVIDER` | `stub` | Provider payment |
| `APP_VERSION` | `0.1.0` | Versi app device |

## Endpoints

| Method | Path | Deskripsi |
|--------|------|-----------|
| `GET` | `/` | Health check |
| `GET` | `/config` | Bundle config device (assignment, booth, campaign, profiles, frames, voucher count) |
| `GET` | `/config/campaign` | Campaign aktif |
| `GET` | `/config/profiles` | Camera & printer profile |
| `GET` | `/templates` | Frame template untuk campaign aktif |
| `GET` | `/devices/me` | Info device sendiri |
| `PATCH` | `/devices/heartbeat` | Heartbeat + health report |
| `POST` | `/sessions` | Mulai sesi (offline-first) |
| `GET` | `/sessions` | Daftar sesi terbaru |
| `GET` | `/sessions/{id}` | Detail sesi |
| `PATCH` | `/sessions/{id}` | Update state sesi |
| `GET` | `/vouchers/{code}` | Validasi voucher (lokal) |
| `POST` | `/vouchers/{code}/redeem` | Redeem voucher (offline-first) |
| `POST` | `/payments` | Buat payment (offline-first) |
| `GET` | `/payments` | Daftar payment device |
| `GET` | `/payments/{id}` | Detail payment |
| `GET` | `/sync/status` | Status sync + antrian pending |
| `POST` | `/sync/trigger` | Trigger sync manual |

## Alur sync

1. `push_device` — heartbeat/health device → server.
2. `push_outbox` — push operasi tertunda, urut: sessions → logs → payments → vouchers.
3. `pull_config` — refresh config dari server ke SQLite (server menang).
4. `pull_payments` — tarik status payment terbaru (hasil webhook) ke lokal.

## Catatan produksi

- Credential PostgreSQL ada di setiap device; gunakan role read-write khusus
  (bukan superuser) atau VPN jika sensitif.
- Payment webhook tetap diterima admin panel; device mendapatkan status via pull.
- Saat offline, redemption voucher hanya diizinkan jika batch-nya
  `offline_eligible = true`.
- Race inter-device pada voucher dengan kode sama di-resolve "last push wins".
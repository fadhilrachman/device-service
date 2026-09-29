# Our Lil Photobooth — Device Service

Service utama yang berjalan di setiap device photobooth (Raspberry Pi / SBC).
Semua operasi baca/tulis langsung ke PostgreSQL yang sama dengan admin panel
(backend2). Tidak ada database lokal / sync engine — offline ditangani
client-side oleh kiosk.

```
┌───────────────────────────────────────────────┐
│                Raspberry Pi                    │
│   FastAPI (device-service) ──► PostgreSQL      │
│        (Neon — DB yang sama dgn admin)         │
└────────────────────────────────────────────────┘
```

## Arsitektur

- **PostgreSQL (REMOTE_DATABASE_URL)** — satu-satunya database (sama dengan
  admin panel). Semua endpoint baca/tulis langsung ke sini: sessions,
  session_device_logs, payments, voucher, heartbeat, serta config
  (campaigns, booths, profiles, frame templates, vouchers, assignments).

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env   # lalu isi REMOTE_DATABASE_URL
uvicorn main:app --host 0.0.0.0 --port 8000
```

## Environment

| Variable | Default | Keterangan |
|----------|---------|------------|
| `REMOTE_DATABASE_URL` | — | PostgreSQL URL (DB yang sama dengan admin panel) |
| `JWT_SECRET` | *harus diisi* | Secret HS256 yang sama dengan `backend2/.env` untuk memverifikasi token Bearer |
| `PAYMENT_PROVIDER` | `stub` | Provider payment |
| `STORAGE_BASE_URL` | `https://storage.arnatech.id` | Base URL storage service (proxy upload API) |
| `SSO_BASE_URL` | `https://sso.arnatech.id/api` | Base URL SSO — digunakan proxy `/auth/device/*` |
| `APP_VERSION` | `0.1.0` | Versi app device |

## Auth

Semua endpoint kecuali `/`, `/docs`, `/redoc`, `/openapi.json`, dan onboarding
device (`POST /auth/device/authorize/`, `/token/`, `/refresh/`) mewajibkan header
`Authorization: Bearer <token>`. Identitas device tidak datang dari env — diambil
dari claim `device_id` token (UUID `devices.id` di database); token tanpa claim
itu ditolak 401 di endpoint device. Token operator (untuk `/verification/` dan
`/revoke/`) tidak membawa `device_id`. Mint token untuk testing lokal:

```powershell
# di repo backend2
.\.venv\Scripts\python.exe -c "from lib.token import create_token; print(create_token('test-user', 'org-1'))"
```

## Endpoints

> Semua endpoint di bawah (kecuali `/`) memerlukan `Authorization: Bearer <token>`.

| Method | Path | Deskripsi |
|--------|------|-----------|
| `GET` | `/` | Health check |
| `GET` | `/config` | Bundle config device (device, camera/printer profiles, frames, voucher count) |
| `GET` | `/config/campaign` | Campaign aktif device (via assignment) |
| `GET` | `/config/profiles` | Camera & printer profile |
| `GET` | `/templates` | Frame template untuk campaign aktif |
| `GET` | `/devices/me` | Info device sendiri |
| `PATCH` | `/devices/heartbeat` | Heartbeat + health report |
| `POST` | `/sessions` | Mulai sesi |
| `GET` | `/sessions` | Daftar sesi terbaru device ini |
| `GET` | `/sessions/{id}` | Detail sesi |
| `PATCH` | `/sessions/{id}` | Update state sesi |
| `GET` | `/vouchers` | Daftar voucher campaign aktif milik device (filter dari token, untuk download lokal) |
| `POST` | `/vouchers/{code}/redeem` | Redeem voucher |
| `POST` | `/payments` | Buat payment |
| `GET` | `/payments` | Daftar payment device |
| `GET` | `/payments/{id}` | Detail payment |
| `POST` | `/api/files/upload` | Inisiasi upload file (multipart presign) |
| `POST` | `/api/files/{file_id}/parts/presign` | Presign parts upload |
| `POST` | `/api/files/{file_id}/complete` | Selesaikan upload multipart |
| `POST` | `/api/files/{file_id}/abort` | Batalkan upload |
| `POST` | `/auth/device/authorize/` | Device authorization — mulai login (proxi ke SSO) |
| `POST` | `/auth/device/verification/` | Approve/deny oleh operator (Bearer, proxi ke SSO) |
| `POST` | `/auth/device/token/` | Poll token saat device disetujui (proxi ke SSO) |
| `POST` | `/auth/device/refresh/` | Rotasi refresh token (proxi ke SSO) |
| `POST` | `/auth/device/revoke/` | Revoke device oleh operator (Bearer, proxi ke SSO) |

## Catatan produksi

- Credential PostgreSQL ada di setiap device; gunakan role read-write khusus
  (bukan superuser) atau VPN jika sensitif.
- Payment webhook tetap diterima admin panel; device membaca status terbaru
  langsung dari database bersama via `POST /payments/{id}/refresh`.
- Offline ditangani client-side oleh kiosk (service ini selalu butuh koneksi DB).
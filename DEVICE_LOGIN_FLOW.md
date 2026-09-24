# Device Login Flow

Diagram berikut menggambarkan alur OAuth 2.0 Device Authorization Grant untuk perangkat publik (photobooth, kiosk, POS, scanner) yang dipairing oleh operator melalui Arna SSO.

## Diagram Pairing & Token

```mermaid
flowchart LR
    A([Mulai]) --> B{Ada kredensial\\nterintegrasi?}
    B -- Ya --> R
  
    subgraph DEVICE [Kiosk / Perangkat]
        direction TB
        C[POST /api/auth/device/authorize/\nclient_id + organization_id + tenant_id\n+ audience photobooth-api]
        C --> D[SSO mengembalikan\ndevice_code + user_code\nverification_uri + QR]
        D --> E[Tampilkan QR + user_code\n+ URL fallback manual]
        E --> F[Polling POST /api/auth/device/token/\nsesuai interval, mis. 5 detik]
        F --> G{Polling berhasil?}
        G -- pending / slow_down --> F
    end

    subgraph OPERATOR [Operator / Arna SSO]
        direction TB
        H[Scan QR atau masukkan user_code] --> I[Login SSO]
        I --> J[Verifikasi perangkat, organisasi,\ntenant, dan scope]
        J --> K[approve /api/auth/device/verification/\npermission device.activate]
        K --> F
    end

    G -- access_denied / expired_token /\ninvalid_grant --> L([Bersihkan state pairing\nkembali ke layar QR])

    subgraph STORE [Penyimpanan Aman]
        direction TB
        M[Simpan access + refresh token\nhanya di keychain / TPM / server]
    end

    G -- sukses --> M --> R([Paired & siap beroperasi])

```

## Diagram Runtime & Lifecycle

```mermaid
flowchart LR
    R([Paired & siap beroperasi]) --> S[Panggil Photobooth API\nAuthorization: Bearer DEVICE_ACCESS_TOKEN]

    subgraph VALIDATE [Validasi Backend Photobooth]
        direction TB
        V1{RS256 + issuer SSO valid?}
        V2{Belum expired?}
        V3{Audience = photobooth-api?}
        V4{token_type = device?}
        V5{device_id, organization_id,\ntenant_id ada & valid?}
        V6{Scope terpenuhi?\\ncth. photobooth.session}
        V7{Registrasi device aktif?\\n& event ditugaskan ke device}
        V1 -- Ya --> V2 -- Ya --> V3 -- Ya --> V4 -- Ya --> V5 -- Ya --> V6 -- Ya --> V7
        V7 -- Ya --> OK([Akses diterima])
        V1 -- Tidak --> Rej
        V2 -- Tidak --> Rej
        V3 -- Tidak --> Rej
        V4 -- Tidak --> Rej
        V5 -- Tidak --> Rej
        V6 -- Tidak --> Rej
        V7 -- Tidak --> Rej
        Rej([Tolak akses])
    end

    OK --> T{Akses token hendak\\nberakhir?}
    T -- Ya --> U[Refesh POST /api/auth/device/refresh/\nrotasi token atomik]
    U --> W{Refresh berhasil?}
    W -- Ya --> S
    W -- Tidak --> X([Hapus kredensial\nkembali ke pairing])

    T -- Tidak --> Y[Operasi: kiosk siap layani visitor\ndan proses pembayaran]
    Y --> Z{Terdapat logout / revoke?}
    Z -- Logout lokal --> X
    Z -- Revoke dashboard\n/api/auth/device/revoke --> X
    Z -- Tidak --> Y
```

## Catatan Kunci

- `device_code` bersifat rahasia, jangan ditampilkan ke visitor atau di-log.
- Polling tidak boleh lebih cepat dari `interval`, dan harus memperlambat saat `slow_down`.
- Token hanya untuk API `photobooth-api`; Commerce dan File Manager memakai service credential backend terpisah.
- Payment hanya boleh dipercaya dari event backend (Payment Router via Pulsar), bukan dari browser visitor.
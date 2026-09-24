# Arnatech Device Login Implementation Guide

## Purpose

Use this guide for public devices such as photobooths, kiosks, POS terminals, scanners, and event devices. Visitors do not sign in. Instead, an authorized organization operator pairs the physical device once through Arna SSO.

The implementation uses the OAuth 2.0 Device Authorization Grant. It does **not** use an operator's personal app token.

## Architecture and ownership

| Concern | Owner | Rule |
| --- | --- | --- |
| User identity, organizations, permissions, device registration, revocation | Arna SSO | Device credentials are issued and managed here. |
| Tenant UUID and tenant-owned application data | ArnaSite | Use the public UUID `tenant_id`, not the legacy numeric tenant `id`. |
| Photobooth business API | Photobooth backend | Validate device credentials and scope every record by organization and tenant. |
| Commerce and File Manager access | Photobooth backend | Use separate service credentials; do not give a kiosk token direct access. |

Use `photobooth-api` as the device token audience. Do not use `photobooth`.

## 1. Provision the operator, organization, and tenant

1. The operator registers through the normal SSO account flow.
2. The operator completes email OTP verification and signs in.
3. In the Account dashboard, create or select the organization/company.
4. Create or select the ArnaSite tenant associated with that organization.
5. Save these values for the device configuration:

   - `organization_id`: the SSO organization UUID.
   - `tenant_id`: the public ArnaSite tenant UUID.

`tenant_id` must be a UUID. Do not send the ArnaSite legacy numeric `id` to SSO.

The operator who approves pairing must have the `device.activate` permission for the organization.

## 2. Generate a stable device identity

Each physical installation needs a unique and stable `client_id`. Keep it through normal software restarts. For example:

```text
photobooth-ols-cfd-001
```

Use a new `client_id` when a device is permanently replaced. Do not share one client ID across multiple physical devices.

## 3. Request device authorization

When the device is not paired, call Arna SSO from the device application or its trusted backend:

```http
POST https://sso.arnatech.id/api/auth/device/authorize/
Content-Type: application/json
```

```json
{
  "client_id": "photobooth-ols-cfd-001",
  "device_name": "OLS CFD Photobooth 001",
  "organization_id": "ORG_UUID",
  "tenant_id": "TENANT_UUID",
  "audience": "photobooth-api",
  "scopes": ["photobooth.session"]
}
```

SSO returns a short-lived, one-time pairing result similar to:

```json
{
  "device_code": "SECRET_DEVICE_CODE",
  "user_code": "ABCD-EFGH",
  "verification_uri": "https://sso.arnatech.id/...",
  "verification_uri_complete": "https://sso.arnatech.id/...code=ABCD-EFGH",
  "expires_in": 600,
  "interval": 5
}
```

Treat `device_code` as a secret. Do not display it, log it, or send it to the visitor browser.

## 4. Build the kiosk pairing screen

Display all of the following:

- A QR code containing `verification_uri_complete`.
- The readable `user_code`.
- A manual fallback URL, `verification_uri`.
- A clear waiting state, for example: “Scan this code with an authorized Arna account.”

Suggested states:

```text
Not paired -> Pairing code displayed -> Waiting for approval -> Paired and ready
                                                   |-> Denied, expired, or failed -> Start again
```

The visitor-facing experience remains login-free. Only an authorized operator scans the code or enters the code manually.

## 5. Approve pairing in the operator browser

The operator opens the QR URL, signs in to SSO if needed, verifies the displayed device, organization, tenant, and requested scopes, then approves it.

The approval request is:

```http
POST https://sso.arnatech.id/api/auth/device/verification/
Authorization: Bearer OWNER_ACCESS_TOKEN
Content-Type: application/json
```

```json
{
  "user_code": "ABCD-EFGH",
  "organization_id": "ORG_UUID",
  "action": "approve"
}
```

SSO is responsible for confirming the operator belongs to the organization and has `device.activate`. The requested tenant is already bound to the pending device authorization and must not be replaced from browser input.

## 6. Poll for the device token

After the device authorization request, poll at the returned interval:

```http
POST https://sso.arnatech.id/api/auth/device/token/
Content-Type: application/json
```

```json
{
  "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
  "device_code": "SECRET_DEVICE_CODE"
}
```

Handle outcomes as follows:

| Result | Device behavior |
| --- | --- |
| `authorization_pending` | Continue waiting at the configured interval. |
| `slow_down` | Increase the polling interval before retrying. |
| `access_denied`, `expired_token`, `invalid_grant` | Clear pairing state and return to the QR screen. |
| Success | Securely persist the access token and rotated refresh token. |

Do not poll more frequently than `interval`.

## 7. Store and refresh credentials securely

Store device access and refresh credentials only in trusted device storage, such as an operating-system keychain, TPM-backed secret storage, or a server-side kiosk session.

Do not store long-lived credentials in browser localStorage, a public QR payload, source code, or environment files shipped to the visitor device.

Refresh before the access token expires:

```http
POST https://sso.arnatech.id/api/auth/device/refresh/
Content-Type: application/json
```

```json
{
  "refresh_token": "CURRENT_REFRESH_TOKEN"
}
```

Refresh tokens rotate. Replace the stored access token and refresh token atomically. If refresh fails, clear local credentials and begin pairing again.

Where supported by the hardware, bind the device credential to a device-held key with DPoP or mTLS.

## 8. Authorize calls in the photobooth backend

The device calls the photobooth API with:

```http
Authorization: Bearer DEVICE_ACCESS_TOKEN
```

The photobooth backend must reject a token unless all of these checks pass:

- RS256 signature and SSO issuer are valid.
- Token is not expired.
- Audience is exactly `photobooth-api`.
- `token_type` equals `device`.
- `device_id`, `organization_id`, and `tenant_id` claims exist and are valid.
- Required scope, for example `photobooth.session`, is present.
- The SSO device registration is active.
- The requested event, station, or resource is assigned to that device.

Persist `organization_id` and `tenant_id` on every tenant-owned photobooth session, photo job, payment intent, and entitlement-sensitive record. Queries and mutations must constrain both identifiers.

## 9. Process payments safely

The kiosk token is only for the photobooth API. The photobooth backend uses its own narrowly scoped service credential to create Commerce payment intents or request File Manager storage.

For every QRIS payment:

1. The photobooth backend derives `organization_id` and `tenant_id` from the validated device token.
2. It creates the payment/invoice through the appropriate trusted backend integration.
3. Payment Router receives provider callbacks and publishes payment facts through Pulsar.
4. The photobooth backend processes events idempotently and activates the purchased session only after the authoritative payment event.

Never trust a payment result sent by a visitor browser as proof of payment.

## 10. Logout, revocation, and replacement

### Local kiosk logout

1. Delete locally stored access token, refresh token, and pairing state.
2. Return to the QR pairing screen.

### Remote operator action

Device registration, inventory, reassignment, and revocation are managed in the Account dashboard. Dashboard revocation calls:

```http
POST https://sso.arnatech.id/api/auth/device/revoke/
```

After revocation, the device must fail on its next refresh and return to pairing. Keep device access tokens short-lived so revocation takes effect promptly.

## Implementation checklist

- [ ] Normal SSO operator registration and verified email flow are used.
- [ ] Organization UUID and ArnaSite public tenant UUID are configured.
- [ ] Every physical device has its own stable client ID.
- [ ] The kiosk renders QR and manual-code fallback screens.
- [ ] The kiosk honors polling interval and handles expiry/denial safely.
- [ ] Tokens are stored in secure device or server-side storage.
- [ ] Refresh-token rotation is atomic.
- [ ] The photobooth API validates issuer, signature, audience, token type, scope, device, organization, tenant, and active registration.
- [ ] Tenant-owned records always persist and query by both organization and tenant.
- [ ] Commerce and File Manager calls use backend service credentials, not kiosk credentials.
- [ ] Local logout and dashboard-driven remote revocation have been tested.

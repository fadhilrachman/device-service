# Kiosk Device Login

This guide defines the kiosk-side implementation for a photobooth, POS,
scanner, CLI, agent, or other unattended Arnatech device. It applies OAuth 2.0
Device Authorization Grant using the Arna SSO API base URL:

```text
https://sso.arnatech.id/api
```

The kiosk has no human sign-in screen. A visitor can use the kiosk without an
account, while the installed machine authenticates as a tenant-bound device.

## Scope and ownership

The kiosk implements only:

1. QR-code login with a manual-code fallback.
2. Device-token polling and refresh.
3. Local logout.

The account dashboard owns device administration:

- approving and registering a device;
- assigning the device to an organization and tenant;
- listing device registrations; and
- revoking or unpairing lost, retired, or compromised devices.

Local logout and dashboard revoke have different effects. Local logout removes
credentials from one machine. Dashboard revoke invalidates the device
registration and its refresh credentials everywhere.

## Prerequisites

Provision each installed machine with a stable, unique `client_id`. The kiosk
also needs the tenant UUID, its permitted audience, and the minimum required
scopes. Do not use a person's access token, a browser session, or a generic
service token as the kiosk identity.

Example values:

```text
client_id: ols-photobooth-cfd-01
device_name: OLS Photobooth — CFD 01
tenant_id: <OLS tenant UUID>
audience: photobooth
scopes: ["photobooth.session.write", "commerce.checkout.create"]
```

Store a device access token and refresh token only in the operating system's
secure device storage or an equivalent encrypted secret store. Never expose
them to a browser, visitor UI, log, analytics event, or URL.

## 1. Start device login

When no valid local device credential exists, call:

```http
POST /auth/device/authorize/
Content-Type: application/json
```

```json
{
  "client_id": "ols-photobooth-cfd-01",
  "device_name": "OLS Photobooth — CFD 01",
  "tenant_id": "<OLS-tenant-uuid>",
  "audience": "photobooth",
  "scopes": [
    "photobooth.session.write",
    "commerce.checkout.create"
  ]
}
```

Optionally include `public_key_thumbprint` when the device supports
proof-of-possession key binding.

The response includes:

```json
{
  "device_code": "<secret opaque value>",
  "user_code": "ABCD-EFGH",
  "verification_uri": "https://sso.arnatech.id/...",
  "verification_uri_complete": "https://sso.arnatech.id/...?...",
  "expires_in": 600,
  "interval": 5
}
```

Render `verification_uri_complete` as a QR code. Also show `user_code` and a
short fallback instruction, such as: **Open SSO device approval and enter this
code: ABCD-EFGH**.

The `device_code` is a secret used by the machine only. The `user_code` is the
short code a human may enter in the approval browser.

## 2. Approval occurs in the account dashboard

The operator scans the QR code or opens the verification page and signs in to
SSO. SSO reuses the operator's existing browser session when possible.

An organization owner, superuser, or member with `device.activate` chooses the
owning organization and approves the code. The dashboard calls:

```http
POST /auth/device/verification/
Authorization: Bearer <operator access token>
```

```json
{
  "user_code": "ABCD-EFGH",
  "organization_id": "<OLS-organization-uuid>",
  "action": "approve"
}
```

SSO binds the device to the selected organization, the requested tenant,
audience, and approved scopes. The kiosk must never collect the operator's
password, MFA code, or browser token.

## 3. Poll for the device token pair

Wait at least the returned `interval`, then call:

```http
POST /auth/device/token/
Content-Type: application/json
```

```json
{
  "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
  "device_code": "<secret device_code>"
}
```

Expected polling responses:

| Response | Kiosk behavior |
| --- | --- |
| `authorization_pending` | Keep the QR screen visible and retry after `interval`. |
| `slow_down` | Increase the delay to the returned interval before retrying. |
| `access_denied` | Remove the pending request and show a new QR login. |
| `expired_token` or `invalid_grant` | Remove the pending request and start a new login. |
| `200` | Securely store the returned token pair and enter kiosk mode. |

On success, the response is:

```json
{
  "access_token": "<short-lived device JWT>",
  "refresh_token": "<rotating opaque token>",
  "token_type": "Bearer",
  "expires_in": 900
}
```

The authorization request is one-time. Do not poll or reuse its `device_code`
after success.

## 4. Use and refresh the credential

Call the kiosk's intended backend with:

```http
Authorization: Bearer <access_token>
```

The receiving backend must validate the token's `token_type=device`,
`device_id`, `organization_id` or `org_id`, `tenant_id`, `aud`, and scopes. It
must reject a token with a different audience, tenant, or required scope.

Before the access token expires, rotate it with:

```http
POST /auth/device/refresh/
Content-Type: application/json
```

```json
{
  "refresh_token": "<current refresh token>"
}
```

Persist the replacement refresh token atomically. A used refresh token cannot
be safely reused.

## 5. Local kiosk logout

Local logout should:

1. Cancel any active device-token polling timer.
2. Delete the locally stored access token, refresh token, and pending device
   code from secure storage.
3. Clear in-memory authenticated state.
4. Return to the QR-login screen.

It must not call the normal human `/auth/logout/` endpoint and does not revoke
the server-side device registration. The next operator can pair the same kiosk
through a new QR approval.

## Account-dashboard revoke or unpair

For a machine that is lost, retired, compromised, or must no longer be trusted,
an authorized administrator uses the account dashboard. The dashboard calls:

```http
POST /auth/device/revoke/
Authorization: Bearer <authorized operator token>
```

```json
{
  "device_id": "<registered device UUID>"
}
```

Revocation deactivates the registration and invalidates its refresh
credentials. The device must complete a new QR login and approval before it
can operate again.

## Do not implement

- A username/password, passkey, MFA, Google, or WhatsApp login form on the
  kiosk.
- Parent-domain or shared browser cookies.
- A device credential in `localStorage`, query parameters, QR content, or logs.
- Direct calls from a public kiosk UI to Commerce or File Manager.
- A device-driven revocation workflow; unpairing belongs to the account
  dashboard.

For system-wide tenancy, payment, and device-token validation requirements,
also read the [platform contract](arnatech-platform/references/platform-contract.md).

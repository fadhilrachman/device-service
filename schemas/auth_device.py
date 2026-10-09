from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, UUID4

# Column width on `devices.name`, which the authorize field is written into.
# Enforced here so an oversized value returns a 422 naming the field instead
# of a Postgres 22001 truncation error surfaced as a 409.
NAME_MAX = 160


class DeviceAuthorizeRequest(BaseModel):
    """Authorize input (kiosk-minimal, request body dipertahankan).

    Hanya ``device_name``, ``tenant_id``, dan ``public_key_thumbprint`` yang
    diterima -- sama seperti sebelumnya, tidak diperkaya mengikuti
    backend2 ``DeviceCreate`` yang kaya profil. Yang disamakan adalah
    *konsep dan validasi*: `scopes` dan `audience` tidak ada di schema
    (grant selalu memakai fixed server-side set + audience, pengirim field
    tersebut dapat 422), dan `client_id`/`device_code` selalu generate
    server-side sehingga tidak diterima dari client.
    """

    # Mirrors backend2 DeviceCreate: a stale client still sending `scopes`,
    # `audience` or `client_id` gets a 422 naming the field instead of its value
    # being silently dropped, so the two services cannot diverge in how they
    # treat the same request.
    model_config = ConfigDict(extra="forbid")

    device_name: str = Field(max_length=NAME_MAX)
    tenant_id: UUID4
    public_key_thumbprint: Optional[str] = Field(
        default=None,
        description="Optional RFC 7638 JWK thumbprint for proof-of-possession binding.",
    )

    @classmethod
    def model_json_schema(cls, *args, **kwargs):
        schema = super().model_json_schema(*args, **kwargs)
        if "properties" in schema:
            schema["properties"].pop("client_id", None)
        if "required" in schema:
            schema["required"] = [r for r in schema["required"] if r != "client_id"]
        return schema


class DeviceAuthorizeResponse(BaseModel):
    client_id: str
    device_code: str
    user_code: str
    verification_uri: str
    verification_uri_complete: str
    expires_in: int
    interval: int


class DeviceVerificationRequest(BaseModel):
    user_code: str
    organization_id: UUID4
    action: Literal["approve", "deny"]


class DeviceVerificationResponse(BaseModel):
    status: str
    device_id: UUID4
    tenant_id: UUID4


class DeviceTokenRequest(BaseModel):
    grant_type: Literal["urn:ietf:params:oauth:grant-type:device_code"]
    device_code: str = Field(
        description="Opaque device_code returned by authorize; never the human user_code."
    )


class DeviceTokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str
    expires_in: int


class DeviceRefreshRequest(BaseModel):
    refresh_token: str = Field(description="Current opaque device refresh token.")


class DeviceRevokeRequest(BaseModel):
    device_id: UUID4


class DevicePasswordVerifyRequest(BaseModel):
    """Kiosk password check. Identity comes from the Bearer token's client_id
    claim (see lib.device_identity), so the body carries only ``password``."""

    model_config = ConfigDict(extra="forbid")

    password: str = Field(min_length=1, max_length=100)


class DevicePasswordVerifyResponse(BaseModel):
    success: bool
    message: str
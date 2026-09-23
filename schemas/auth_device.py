from typing import Literal, Optional

from pydantic import BaseModel, Field, UUID4


class DeviceAuthorizeRequest(BaseModel):
    client_id: str
    device_name: str
    tenant_id: UUID4
    audience: str
    scopes: list[str]
    public_key_thumbprint: Optional[str] = Field(
        default=None,
        description="Optional RFC 7638 JWK thumbprint for proof-of-possession binding.",
    )


class DeviceAuthorizeResponse(BaseModel):
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
import os

import httpx
from dotenv import load_dotenv


load_dotenv()

SSO_BASE_URL = os.getenv("SSO_BASE_URL", "https://sso.arnatech.id/api").rstrip("/")


class SSOError(Exception):
    def __init__(self, message: str, status_code: int | None = None):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


class SSOClient:
    def __init__(self, base_url: str = SSO_BASE_URL):
        self.base_url = base_url.rstrip("/")

    def request(self, method: str, path: str, json=None, access_token: str | None = None) -> httpx.Response:
        headers = {}
        if access_token:
            headers["Authorization"] = f"Bearer {access_token}"
        try:
            response = httpx.request(
                method,
                f"{self.base_url}{path}",
                headers=headers,
                json=json,
                timeout=60.0,
            )
        except httpx.HTTPError as exc:
            raise SSOError(f"SSO service unreachable: {exc}")
        return response

    def authorize(self, payload: dict) -> httpx.Response:
        return self.request("POST", "/auth/device/authorize/", json=payload)

    def verification(self, payload: dict, access_token: str) -> httpx.Response:
        return self.request(
            "POST",
            "/auth/device/verification/",
            json=payload,
            access_token=access_token,
        )

    def token(self, payload: dict) -> httpx.Response:
        return self.request("POST", "/auth/device/token/", json=payload)

    def refresh(self, payload: dict) -> httpx.Response:
        return self.request("POST", "/auth/device/refresh/", json=payload)

    def revoke(self, payload: dict, access_token: str) -> httpx.Response:
        return self.request(
            "POST",
            "/auth/device/revoke/",
            json=payload,
            access_token=access_token,
        )
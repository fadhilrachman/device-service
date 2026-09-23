import os

import httpx
from dotenv import load_dotenv


load_dotenv()

STORAGE_BASE_URL = os.getenv("STORAGE_BASE_URL", "https://storage.arnatech.id").rstrip("/")


class StorageError(Exception):
    def __init__(self, message: str, status_code: int | None = None):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


class StorageClient:
    def __init__(self, access_token: str, base_url: str = STORAGE_BASE_URL):
        self.base_url = base_url.rstrip("/")
        self.headers = {"Authorization": f"Bearer {access_token}"}

    def request(self, method: str, path: str, json=None) -> httpx.Response:
        try:
            response = httpx.request(method, f"{self.base_url}{path}", headers=self.headers, json=json, timeout=600.0)
        except httpx.HTTPError as exc:
            raise StorageError(f"Storage service unreachable: {exc}")
        return response

    def initiate_upload(self, payload: dict) -> httpx.Response:
        return self.request("POST", "/api/files/upload", json=payload)

    def presign_parts(self, file_id: str, parts: list[int]) -> httpx.Response:
        return self.request("POST", f"/api/files/{file_id}/parts/presign", json={"parts": parts})

    def complete_upload(self, file_id: str, parts: list[dict]) -> httpx.Response:
        return self.request("POST", f"/api/files/{file_id}/complete", json={"parts": parts})

    def abort_upload(self, file_id: str) -> httpx.Response:
        return self.request("POST", f"/api/files/{file_id}/abort")
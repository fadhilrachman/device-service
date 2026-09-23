from typing import Optional

from pydantic import BaseModel, Field


class UploadInitiateRequest(BaseModel):
    filename: Optional[str] = Field(default=None, max_length=255)
    size_bytes: int = Field(ge=1)
    mime_type: Optional[str] = Field(default=None, max_length=255)
    owner_scope: str = "user"
    visibility: str = "private"
    folder_id: Optional[str] = None


class PresignPartsRequest(BaseModel):
    parts: list[int] = Field(min_length=1)


class CompleteUploadPart(BaseModel):
    part_number: int = Field(ge=1)
    etag: str = Field(min_length=1, max_length=255)


class CompleteUploadRequest(BaseModel):
    parts: list[CompleteUploadPart] = Field(min_length=1)
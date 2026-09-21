from typing import TypeVar, Generic, Optional

from pydantic import BaseModel
from fastapi import Request
from fastapi.responses import JSONResponse

T = TypeVar("T")


class PaginationInfo(BaseModel):
    total_data: int
    page: int
    limit: int


class BaseListResponse(BaseModel, Generic[T]):
    message: str
    data: list[T]
    pagination: Optional[PaginationInfo] = None


class BadRequestError(Exception):
    def __init__(self, message: str, errors: Optional[dict[str, list[str]]] = None):
        self.message = message
        self.errors = errors


async def bad_request_exception_handler(request: Request, exc: BadRequestError):
    detail = {"message": exc.message}
    if exc.errors:
        detail["errors"] = exc.errors
    return JSONResponse(status_code=400, content={"detail": detail})
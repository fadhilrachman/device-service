from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import JSONResponse

from lib.storage import StorageClient, StorageError
from schemas.upload import (
    CompleteUploadRequest,
    PresignPartsRequest,
    UploadInitiateRequest,
)

router = APIRouter(prefix="/api", tags=["upload-workflow"])


def _get_access_token(request: Request) -> str:
    token = getattr(request.state, "sso_access_token", None)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Valid access token is required.")
    return token


def _forward(response) -> JSONResponse:
    try:
        body = response.json()
    except Exception:
        body = None
    return JSONResponse(status_code=response.status_code, content=body)


@router.post("/files/upload", status_code=status.HTTP_201_CREATED)
def initiate_upload(payload: UploadInitiateRequest, request: Request):
    try:
        response = StorageClient(_get_access_token(request)).initiate_upload(payload.model_dump(exclude_none=True))
    except StorageError as exc:
        raise HTTPException(status_code=exc.status_code or status.HTTP_502_BAD_GATEWAY, detail=exc.message)
    return _forward(response)


@router.post("/files/{file_id}/parts/presign")
def presign_parts(file_id: str, payload: PresignPartsRequest, request: Request):
    try:
        response = StorageClient(_get_access_token(request)).presign_parts(file_id, payload.parts)
    except StorageError as exc:
        raise HTTPException(status_code=exc.status_code or status.HTTP_502_BAD_GATEWAY, detail=exc.message)
    return _forward(response)


@router.post("/files/{file_id}/complete")
def complete_upload(file_id: str, payload: CompleteUploadRequest, request: Request):
    try:
        response = StorageClient(_get_access_token(request)).complete_upload(file_id, [part.model_dump() for part in payload.parts])
    except StorageError as exc:
        raise HTTPException(status_code=exc.status_code or status.HTTP_502_BAD_GATEWAY, detail=exc.message)
    return _forward(response)


@router.post("/files/{file_id}/abort")
def abort_upload(file_id: str, request: Request):
    try:
        response = StorageClient(_get_access_token(request)).abort_upload(file_id)
    except StorageError as exc:
        raise HTTPException(status_code=exc.status_code or status.HTTP_502_BAD_GATEWAY, detail=exc.message)
    return _forward(response)
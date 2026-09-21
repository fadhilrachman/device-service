from fastapi import APIRouter, Depends

from config import DEVICE_CODE, SYNC_INTERVAL_SECONDS, resolve_device_id
from database import get_db
from schemas.sync import SyncStatusResponse
from sync import engine

router = APIRouter(prefix="/sync", tags=["sync"])


@router.get("/status", response_model=SyncStatusResponse)
def sync_status(db=Depends(get_db)):
    pending, total = engine.outbox_counts()
    return SyncStatusResponse(
        online=engine.online or False,
        last_sync_at=engine.last_sync_at,
        pending_push=pending,
        synced_push=total - pending,
        last_result=engine.last_result,
        sync_interval_seconds=SYNC_INTERVAL_SECONDS,
        device_id=resolve_device_id(),
        device_code=DEVICE_CODE,
    )


@router.post("/trigger", response_model=dict)
def trigger_sync():
    return engine.run_once()
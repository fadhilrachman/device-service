from typing import Optional
from pydantic import BaseModel


class SyncStatusResponse(BaseModel):
    online: bool
    last_sync_at: Optional[object] = None
    pending_push: int
    synced_push: int
    last_result: Optional[dict] = None
    sync_interval_seconds: Optional[int] = None
    device_id: Optional[str] = None
    device_code: Optional[str] = None
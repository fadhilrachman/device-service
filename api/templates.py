from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from api.config import _active_campaign, _resolve_frames
from database import get_db
from lib.device_identity import require_request_device_id
from schemas.config import FrameTemplateResponse

router = APIRouter(prefix="/templates", tags=["templates"])


@router.get("", response_model=list[FrameTemplateResponse])
def list_templates(request: Request, db: Session = Depends(get_db)):
    campaign = _active_campaign(db, require_request_device_id(request))
    return _resolve_frames(db, campaign)
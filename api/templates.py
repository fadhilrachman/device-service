from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from api.config import _active_campaign, _resolve_frames
from database import get_db
from schemas.config import FrameTemplateResponse

router = APIRouter(prefix="/templates", tags=["templates"])


@router.get("", response_model=list[FrameTemplateResponse])
def list_templates(db: Session = Depends(get_db)):
    campaign = _active_campaign(db)
    return _resolve_frames(db, campaign)
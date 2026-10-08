from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from database import get_db
from lib.device_identity import require_request_device_id
from lib.soft_delete import active, get_active_or_404
from models.campaign import Campaign
from models.session import SessionModel, SessionState
from schemas.campaign import CampaignSessionLimitResponse

router = APIRouter(prefix="/campaigns", tags=["campaigns"])


@router.get("/{campaign_id}/session-limit", response_model=CampaignSessionLimitResponse)
def get_campaign_session_limit(campaign_id: str, request: Request, db: Session = Depends(get_db)):
    """How much of a campaign's session quota is used (completed sessions only).

    Kiosk-authenticated like the other operational endpoints. Soft-deleted
    sessions never count; a null limit means unlimited (remaining is null).
    """
    require_request_device_id(db, request)
    campaign = get_active_or_404(db, Campaign, campaign_id, "Campaign")
    used = (
        db.query(SessionModel)
        .filter(
            SessionModel.campaign_id == campaign.id,
            SessionModel.state == SessionState.COMPLETE,
            active(SessionModel),
        )
        .count()
    )
    limit = campaign.session_limit
    return CampaignSessionLimitResponse(
        campaign_id=campaign.id,
        session_limit=limit,
        used=used,
        remaining=None if limit is None else max(limit - used, 0),
    )

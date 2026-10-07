from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from api.config import _active_campaign, _device_vouchers
from database import get_db
from lib.device_identity import require_request_device_id
from lib.time import wib_now
from models.session import SessionModel
from models.voucher import Voucher
from schemas.voucher import VoucherRedeemRequest, VoucherResponse

router = APIRouter(prefix="/vouchers", tags=["vouchers"])


def _to_response(db: Session, voucher: Voucher) -> VoucherResponse:
    offline_eligible = voucher.batch.offline_eligible if voucher.batch else False
    response = VoucherResponse.model_validate(voucher)
    response.offline_eligible = offline_eligible
    return response


@router.get("", response_model=list[VoucherResponse])
def list_vouchers(request: Request, limit: int = 100, offset: int = 0, db: Session = Depends(get_db)):
    """List vouchers for the calling device's active campaign.

    Both filters come from the access token, never from query params:
    ``vouchers.device_id`` must equal the device resolved from the token ``client_id`` claim and the
    voucher's batch must belong to the device's active campaign (resolved via
    its active assignment -> booth -> campaign). For the kiosk to download its
    voucher data locally.
    """
    device_id = require_request_device_id(db, request)
    campaign = _active_campaign(db, device_id)
    if not campaign:
        raise HTTPException(
            status_code=404,
            detail="No active campaign for this device: no assignment or the assignment window has expired.",
        )
    items = (
        _device_vouchers(db, device_id, campaign)
        .order_by(Voucher.created_at.desc(), Voucher.id.desc())
        .offset(max(0, offset))
        .limit(max(1, min(limit, 1000)))
        .all()
    )
    return [_to_response(db, v) for v in items]


@router.post("/{code}/redeem", response_model=VoucherResponse)
def redeem_voucher(
    code: str, payload: VoucherRedeemRequest, db: Session = Depends(get_db)
):
    if not db.get(SessionModel, payload.session_id):
        raise HTTPException(status_code=404, detail="Session not found.")

    voucher = db.query(Voucher).filter(Voucher.code == code).first()
    if not voucher:
        raise HTTPException(status_code=404, detail="Voucher not found.")

    now = wib_now()
    if (
        voucher.status == "available"
        and voucher.expires_at is not None
        and voucher.expires_at <= now
    ):
        raise HTTPException(status_code=409, detail="Voucher has expired.")
    if voucher.status == "expired":
        raise HTTPException(status_code=409, detail="Voucher has expired.")
    if voucher.status != "available":
        raise HTTPException(status_code=409, detail="Voucher is already used or voided.")

    return _to_response(db, voucher)

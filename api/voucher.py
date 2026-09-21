from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from database import get_db
from lib.outbox import enqueue
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


def _mark_expired(db: Session, voucher: Voucher) -> VoucherResponse:
    voucher.status = "expired"
    enqueue(db, "vouchers", voucher.id)
    db.commit()
    return _to_response(db, voucher)


@router.get("/{code}", response_model=VoucherResponse)
def get_voucher(code: str, db: Session = Depends(get_db)):
    voucher = db.query(Voucher).filter(Voucher.code == code).first()
    if not voucher:
        raise HTTPException(status_code=404, detail="Voucher not found.")

    now = wib_now()
    if (
        voucher.status == "available"
        and voucher.expires_at is not None
        and voucher.expires_at <= now
    ):
        return _mark_expired(db, voucher)
    return _to_response(db, voucher)


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
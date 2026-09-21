from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from config import resolve_device_id
from database import get_db
from lib.outbox import enqueue
from lib.payment_gateway import get_gateway
from models.booth import Booth
from models.campaign import Campaign
from models.device import Device
from models.payment import Payment
from schemas.payment import PaymentCreate, PaymentCreateResponse, PaymentResponse
from sync import engine

router = APIRouter(prefix="/payments", tags=["payments"])

VALID_STATUSES = {"pending", "succeeded", "failed", "refunded"}


def _resolve_amount(db: Session, campaign_id: str | None, amount: float | None) -> float:
    if amount is not None:
        return float(amount)
    if campaign_id:
        campaign = db.get(Campaign, campaign_id)
        if not campaign:
            raise HTTPException(status_code=404, detail="Campaign not found.")
        if campaign.price is None:
            raise HTTPException(status_code=400, detail="Campaign has no price; amount is required.")
        return float(campaign.price)
    raise HTTPException(status_code=400, detail="amount is required when campaign has no price.")


@router.post("", response_model=PaymentCreateResponse, status_code=status.HTTP_201_CREATED)
def create_payment(payload: PaymentCreate, db: Session = Depends(get_db)):
    device_id = payload.device_id or resolve_device_id()
    if not db.get(Device, device_id):
        raise HTTPException(status_code=404, detail="Device not found.")
    if payload.booth_id is not None and not db.get(Booth, payload.booth_id):
        raise HTTPException(status_code=404, detail="Booth not found.")

    offline = not engine.is_online()
    db_obj = Payment(
        session_id=payload.session_id,
        booth_id=payload.booth_id,
        campaign_id=payload.campaign_id,
        device_id=device_id,
        amount=_resolve_amount(db, payload.campaign_id, payload.amount),
        method=payload.method,
        status="pending",
    )
    db.add(db_obj)
    try:
        db.flush()
        charge = get_gateway().create_charge(db_obj)
        db_obj.provider_ref = charge["provider_ref"]
        db_obj.provider = get_gateway().name
        if offline:
            db_obj.gateway_payload = {"offline": True}
        enqueue(db, "payments", db_obj.id)
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(db_obj)
    return PaymentCreateResponse(
        payment=PaymentResponse.model_validate(db_obj),
        charge_url=charge["charge_url"],
    )


@router.get("", response_model=dict)
def list_payments(limit: int = 20, db: Session = Depends(get_db)):
    device_id = resolve_device_id()
    items = (
        db.query(Payment)
        .filter(Payment.device_id == device_id)
        .order_by(Payment.created_at.desc())
        .limit(limit)
        .all()
    )
    return {"message": "Success get payments", "data": items}


@router.get("/{id}", response_model=PaymentResponse)
def get_payment(id: str, db: Session = Depends(get_db)):
    db_obj = db.get(Payment, id)
    if not db_obj:
        raise HTTPException(status_code=404, detail="Payment not found.")
    return db_obj
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from config import (
    COMMERCE_BASE_URL,
    COMMERCE_TIMEOUT_SECONDS,
    resolve_device_id,
)
from database import get_db
from lib.commerce import (
    CommerceClient,
    CommerceError,
    decode_token_payload,
    extract_organization_id,
    extract_tenant_id,
    map_commerce_status,
)
from lib.outbox import enqueue
from lib.payment_gateway import GatewayError, get_gateway
from lib.time import wib_now
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
def create_payment(payload: PaymentCreate, request: Request, db: Session = Depends(get_db)):
    device_id = payload.device_id or resolve_device_id()
    if not db.get(Device, device_id):
        raise HTTPException(status_code=404, detail="Device not found.")
    if payload.booth_id is not None and not db.get(Booth, payload.booth_id):
        raise HTTPException(status_code=404, detail="Booth not found.")

    offline = not engine.is_online()
    gateway = get_gateway()
    context: dict | None = None
    if gateway.name == "commerce":
        # Commerce is online-only; fail fast before persisting anything.
        if offline:
            raise HTTPException(
                status_code=503,
                detail="Commerce payment requires an online connection.",
            )
        context = _commerce_context(request)

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
        charge = gateway.create_charge(db_obj, context)
        db_obj.provider_ref = charge["provider_ref"]
        db_obj.provider = gateway.name
        details = dict(charge.get("details") or {})
        if offline:
            details["offline"] = True
        db_obj.gateway_payload = details or None
        enqueue(db, "payments", db_obj.id)
        db.commit()
    except (CommerceError, GatewayError) as exc:
        db.rollback()
        raise _provider_http_error(exc)
    except Exception:
        db.rollback()
        raise
    db.refresh(db_obj)
    return PaymentCreateResponse(
        payment=PaymentResponse.model_validate(db_obj),
        charge_url=charge["charge_url"],
    )


def _commerce_context(request: Request) -> dict:
    """Build the CommerceGateway context from the incoming request.

    Forwards the caller's Bearer token and decodes organization_id / tenant_id
    from the JWT payload already parsed by ProtectTokenMiddleware.
    """
    token_payload = getattr(request.state, "sso_token_payload", None)
    raw_token = getattr(request.state, "sso_access_token", None)
    if not raw_token:
        authorization = request.headers.get("authorization", "")
        parts = authorization.split(" ")
        if len(parts) == 2 and parts[0] == "Bearer" and parts[1]:
            raw_token = parts[1]
            token_payload = decode_token_payload(raw_token)
    if not raw_token:
        raise HTTPException(status_code=401, detail="Bearer token is required.")
    organization_id = extract_organization_id(token_payload or {})
    if not organization_id:
        raise HTTPException(
            status_code=400,
            detail="organization_id claim is missing in the access token.",
        )
    return {
        "bearer_token": raw_token,
        "organization_id": organization_id,
        "tenant_id": extract_tenant_id(token_payload or {}),
    }


def _provider_http_error(exc: Exception) -> HTTPException:
    """Translate gateway/commerce failures to HTTP errors for the kiosk."""
    if isinstance(exc, GatewayError):
        # Local misconfiguration (unmapped campaign, missing context, ...).
        return HTTPException(status_code=400, detail=str(exc))
    if isinstance(exc, CommerceError):
        if exc.status_code and 400 <= exc.status_code < 500:
            return HTTPException(
                status_code=400,
                detail=f"Commerce rejected the request: {exc.message}",
            )
        return HTTPException(
            status_code=502,
            detail=f"Commerce service error: {exc.message}",
        )
    return HTTPException(status_code=500, detail="Payment provider error.")


def _commerce_client(context: dict) -> CommerceClient:
    return CommerceClient(
        context["bearer_token"],
        COMMERCE_BASE_URL,
        timeout=COMMERCE_TIMEOUT_SECONDS,
    )


def _refresh_commerce_state(db: Session, db_obj: Payment, context: dict) -> Payment:
    """Poll Commerce once and persist order/invoice status to the local row."""
    details = dict(db_obj.gateway_payload or {})
    client = _commerce_client(context)
    try:
        order = client.get_order(details["order_id"]) if details.get("order_id") else {}
        invoice = client.get_invoice(details["invoice_id"]) if details.get("invoice_id") else None
    finally:
        client.close()
    new_status = map_commerce_status(order, invoice)
    details["order_status"] = order.get("status")
    if isinstance(invoice, dict):
        details["invoice_status"] = invoice.get("status")
        if invoice.get("paid_at"):
            details["commerce_paid_at"] = invoice.get("paid_at")
    db_obj.gateway_payload = details
    if new_status != db_obj.status:
        db_obj.status = new_status
        if new_status == "succeeded":
            db_obj.paid_at = wib_now()
        enqueue(db, "payments", db_obj.id)
    return db_obj


@router.post("/{id}/refresh", response_model=PaymentResponse)
def refresh_payment(id: str, request: Request, db: Session = Depends(get_db)):
    """Poll Commerce once for a pending payment and persist the result locally.

    The kiosk calls this every few seconds while waiting for the visitor to
    pay on the hosted Xendit page. Idempotent: terminal states are returned
    as-is without calling Commerce.
    """
    db_obj = db.get(Payment, id)
    if not db_obj:
        raise HTTPException(status_code=404, detail="Payment not found.")
    if db_obj.provider != "commerce":
        raise HTTPException(
            status_code=400,
            detail="Only commerce payments can be refreshed.",
        )
    if db_obj.status != "pending":
        return db_obj
    context = _commerce_context(request)
    try:
        _refresh_commerce_state(db, db_obj, context)
        db.commit()
    except CommerceError as exc:
        db.rollback()
        raise _provider_http_error(exc)
    db.refresh(db_obj)
    return db_obj


@router.post("/{id}/cancel", response_model=PaymentResponse)
def cancel_payment(id: str, request: Request, db: Session = Depends(get_db)):
    """Cancel a pending Commerce order and mark the local payment failed."""
    db_obj = db.get(Payment, id)
    if not db_obj:
        raise HTTPException(status_code=404, detail="Payment not found.")
    if db_obj.provider != "commerce":
        raise HTTPException(
            status_code=400,
            detail="Only commerce payments can be cancelled.",
        )
    if db_obj.status != "pending":
        return db_obj
    context = _commerce_context(request)
    client = _commerce_client(context)
    try:
        details = dict(db_obj.gateway_payload or {})
        if details.get("order_id"):
            try:
                client.cancel_order(details["order_id"])
            finally:
                client.close()
        else:
            client.close()
        db_obj.status = "failed"
        details["cancelled_locally"] = True
        db_obj.gateway_payload = details
        enqueue(db, "payments", db_obj.id)
        db.commit()
    except CommerceError as exc:
        db.rollback()
        raise _provider_http_error(exc)
    db.refresh(db_obj)
    return db_obj


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
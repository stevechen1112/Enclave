"""NewebPay checkout + webhook (CG-PAY)."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api import deps
from app.config import settings
from app.crud import crud_tenant
from app.models.billing import BillingRecord
from app.models.tenant import Tenant
from app.models.user import User
from app.services.newebpay import get_payment_provider
from app.services.payment_provider import CheckoutRequest as ProviderCheckoutRequest
from app.services.plan_catalog import PLAN_CATALOG, get_plan, list_checkout_plans

router = APIRouter()
logger = logging.getLogger("enclave.payment")


class PaymentNotifyError(Exception):
    """Webhook 處理失敗；retryable=True 時回 500 讓 NewebPay 重試。"""

    def __init__(self, message: str, *, retryable: bool = True):
        super().__init__(message)
        self.retryable = retryable


class CheckoutRequestBody(BaseModel):
    target_plan: str


class CheckoutResponse(BaseModel):
    mpg_url: str
    form_fields: dict
    trade_no: str


class PlanPriceItem(BaseModel):
    plan: str
    display_name: str
    price_monthly_twd: int | None
    self_checkout: bool


@router.get("/plans", response_model=list[PlanPriceItem])
def list_plans():
    """可售方案與價格（公開）。"""
    items = []
    for plan, cfg in PLAN_CATALOG.items():
        items.append(
            PlanPriceItem(
                plan=plan,
                display_name=cfg["display_name"],
                price_monthly_twd=cfg.get("price_monthly_twd"),
                self_checkout=bool(cfg.get("self_checkout")),
            )
        )
    return items


@router.post("/checkout", response_model=CheckoutResponse)
def create_checkout(
    body: CheckoutRequestBody,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
):
    if current_user.role != "owner" and not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="只有 Owner 可以變更方案")

    if body.target_plan not in list_checkout_plans():
        raise HTTPException(status_code=400, detail="此方案不支援線上結帳")

    if not settings.NEWEBPAY_MERCHANT_ID:
        raise HTTPException(status_code=503, detail="金流尚未設定")

    tenant = db.query(Tenant).filter(Tenant.id == current_user.tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    current_order = PLAN_CATALOG.get(tenant.plan or "pilot", {}).get("order", 0)
    target_order = PLAN_CATALOG[body.target_plan]["order"]
    if target_order <= current_order:
        raise HTTPException(status_code=400, detail="無法降級，請聯繫客服")

    plan_config = get_plan(body.target_plan)
    amount = plan_config.get("price_monthly_twd")
    if not amount or amount <= 0:
        raise HTTPException(status_code=400, detail="方案價格未設定")

    provider = get_payment_provider()
    result = provider.create_checkout(
        ProviderCheckoutRequest(
            tenant_id=str(tenant.id),
            plan=body.target_plan,
            amount=int(amount),
            currency="TWD",
            description=f"Enclave {plan_config['display_name']} 方案月費",
            email=current_user.email or "",
        )
    )

    logger.info(
        "Checkout: tenant=%s plan=%s amount=%s trade_no=%s",
        tenant.id,
        body.target_plan,
        amount,
        result.trade_no,
    )
    return CheckoutResponse(
        mpg_url=result.checkout_url,
        form_fields=result.form_fields,
        trade_no=result.trade_no,
    )


@router.post("/notify")
async def payment_notify(request: Request, db: Session = Depends(deps.get_db)):
    if not settings.NEWEBPAY_HASH_KEY:
        raise HTTPException(status_code=503, detail="Payment not configured")

    form = await request.form()
    form_data = dict(form)

    provider = get_payment_provider()
    try:
        event = provider.verify_webhook(form_data)
    except ValueError as exc:
        logger.warning("Payment webhook verification failed: %s", exc)
        raise HTTPException(status_code=400, detail="驗證失敗") from exc

    try:
        if event.event_type == "payment.success":
            _handle_payment_success(db, event)
        elif event.event_type == "payment.failed":
            _handle_payment_failed(db, event)
    except PaymentNotifyError as exc:
        logger.error("Payment notify processing failed: %s", exc)
        if exc.retryable:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return JSONResponse(content={"received": True})


@router.post("/return")
async def payment_return():
    return JSONResponse(content={"status": "ok"})


def _handle_payment_success(db: Session, event) -> None:
    if not event.tenant_id or not event.plan:
        raise PaymentNotifyError("missing tenant_id or plan", retryable=False)

    try:
        tenant_uuid = UUID(event.tenant_id)
    except ValueError as exc:
        raise PaymentNotifyError(f"invalid tenant_id {event.tenant_id}", retryable=False) from exc

    if event.plan not in PLAN_CATALOG:
        raise PaymentNotifyError(f"invalid plan {event.plan}", retryable=False)

    external_id = event.gateway_trade_no or event.trade_no
    if external_id:
        existing = (
            db.query(BillingRecord)
            .filter(BillingRecord.external_id == external_id)
            .first()
        )
        if existing:
            logger.debug("Duplicate notification for %s", external_id)
            return

    try:
        tenant = (
            db.query(Tenant)
            .filter(Tenant.id == tenant_uuid)
            .with_for_update()
            .first()
        )
        if not tenant:
            raise PaymentNotifyError(f"tenant {event.tenant_id} not found", retryable=True)

        old_plan = tenant.plan
        crud_tenant._apply_plan_fields(tenant, event.plan)
        db.add(tenant)

        plan_config = get_plan(event.plan)
        record = BillingRecord(
            id=uuid.uuid4(),
            tenant_id=tenant_uuid,
            external_id=external_id,
            amount_twd=event.amount,
            currency=event.currency,
            status="paid",
            description=f"升級至 {plan_config['display_name']}",
            plan=event.plan,
            invoice_number=(
                f"INV-{datetime.now(timezone.utc).strftime('%Y%m%d')}-"
                f"{uuid.uuid4().hex[:6].upper()}"
            ),
        )
        db.add(record)
        db.commit()

        logger.info(
            "Tenant %s upgraded: %s → %s amount=%d trade=%s",
            tenant_uuid,
            old_plan,
            event.plan,
            event.amount,
            event.gateway_trade_no,
        )
    except PaymentNotifyError:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        raise PaymentNotifyError(str(exc), retryable=True) from exc


def _handle_payment_failed(db: Session, event) -> None:
    logger.warning(
        "Payment failed: tenant=%s plan=%s trade=%s",
        event.tenant_id,
        event.plan,
        event.trade_no,
    )
    if not event.tenant_id:
        return
    try:
        tenant_uuid = UUID(event.tenant_id)
    except ValueError:
        return

    external_id = event.gateway_trade_no or event.trade_no
    if external_id:
        existing = (
            db.query(BillingRecord)
            .filter(BillingRecord.external_id == external_id)
            .first()
        )
        if existing:
            return

    try:
        record = BillingRecord(
            id=uuid.uuid4(),
            tenant_id=tenant_uuid,
            external_id=external_id,
            amount_twd=event.amount,
            currency=event.currency,
            status="failed",
            description=f"付款失敗 — {event.plan} 方案",
            plan=event.plan,
        )
        db.add(record)
        db.commit()
    except Exception as exc:
        db.rollback()
        raise PaymentNotifyError(str(exc), retryable=True) from exc

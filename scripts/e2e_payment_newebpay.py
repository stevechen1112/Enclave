"""
CG-PAY E2E（模擬 NewebPay notify，無需真實商戶）

閉環：checkout 表單加密 → 偽造 SUCCESS notify → 方案升級 + BillingRecord。
真實商戶驗收仍需 NEWEBPAY_MERCHANT_ID／HASH_* 與藍新測試台。

用法：
  python scripts/e2e_payment_newebpay.py
  python scripts/e2e_payment_newebpay.py --json

產物：artifacts/payment_e2e_last_run.json
"""
from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
ARTIFACT = ROOT / "artifacts" / "payment_e2e_last_run.json"

# 32-byte key / 16-byte IV（僅本機模擬用，非生產憑證）
_TEST_KEY = "abcdefghijklmnopqrstuvwxyz123456"
_TEST_IV = "abcdefghijklmnop"
_TEST_MID = "MS_ENCLAVE_TEST"


def _write(payload: dict) -> None:
    ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
    ARTIFACT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def run() -> int:
    from sqlalchemy.orm import sessionmaker

    from app.api.v1.endpoints.payment import PaymentNotifyError, _handle_payment_success
    from app.config import settings
    from app.db.base_class import Base
    from app.db.session import engine
    from app.models.billing import BillingRecord
    from app.models.tenant import Tenant
    from app.services.newebpay import NewebPayProvider, _aes_encrypt, _sha256_hash
    from app.services.payment_provider import CheckoutRequest, WebhookEvent

    import app.models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    db = Session()

    steps: list[dict] = []
    status = "PASS"
    try:
        # 1. Checkout form（mock settings）
        settings.NEWEBPAY_MERCHANT_ID = _TEST_MID
        settings.NEWEBPAY_HASH_KEY = _TEST_KEY
        settings.NEWEBPAY_HASH_IV = _TEST_IV
        settings.NEWEBPAY_TEST_MODE = True
        settings.BACKEND_BASE_URL = "http://localhost:8000"
        settings.FRONTEND_BASE_URL = "http://localhost:3000"

        tenant = Tenant(name=f"PayE2E-{uuid.uuid4().hex[:6]}", plan="pilot")
        db.add(tenant)
        db.commit()
        db.refresh(tenant)

        provider = NewebPayProvider()
        checkout = provider.create_checkout(
            CheckoutRequest(
                tenant_id=str(tenant.id),
                plan="team",
                amount=2990,
                email="owner@example.com",
                description="Enclave Team E2E",
            )
        )
        steps.append({
            "name": "checkout_form",
            "passed": bool(checkout.trade_no.startswith("ENC") and checkout.form_fields.get("TradeInfo")),
            "trade_no": checkout.trade_no,
        })

        # 2. 模擬藍新 SUCCESS notify（加密 payload）
        gateway_trade = f"GW-{uuid.uuid4().hex[:10]}"
        inner = {
            "Status": "SUCCESS",
            "Result": {
                "MerchantOrderNo": checkout.trade_no,
                "TradeNo": gateway_trade,
                "Amt": 2990,
                "PaymentType": "CREDIT",
                "OrderComment": json.dumps({"tenant_id": str(tenant.id), "plan": "team"}),
            },
        }
        encrypted = _aes_encrypt(json.dumps(inner), _TEST_KEY, _TEST_IV)
        sha = _sha256_hash(encrypted, _TEST_KEY, _TEST_IV)
        event = provider.verify_webhook({
            "Status": "SUCCESS",
            "TradeInfo": encrypted,
            "TradeSha": sha,
        })
        steps.append({
            "name": "verify_webhook",
            "passed": event.event_type == "payment.success" and event.plan == "team",
            "gateway_trade_no": event.gateway_trade_no,
        })

        # 3. 單 transaction 開通
        _handle_payment_success(db, event)
        db.refresh(tenant)
        rec = db.query(BillingRecord).filter(BillingRecord.external_id == gateway_trade).first()
        steps.append({
            "name": "upgrade_and_billing",
            "passed": tenant.plan == "team" and rec is not None and rec.status == "paid",
            "plan": tenant.plan,
            "invoice": getattr(rec, "invoice_number", None),
        })

        # 4. 冪等：重複 notify 不雙開
        before = db.query(BillingRecord).filter(BillingRecord.tenant_id == tenant.id).count()
        _handle_payment_success(db, event)
        after = db.query(BillingRecord).filter(BillingRecord.tenant_id == tenant.id).count()
        steps.append({
            "name": "idempotent_notify",
            "passed": before == after == 1,
            "billing_count": after,
        })

    except PaymentNotifyError as exc:
        status = "FAIL"
        steps.append({"name": "exception", "passed": False, "detail": str(exc)})
    except Exception as exc:
        status = "FAIL"
        steps.append({"name": "exception", "passed": False, "detail": f"{type(exc).__name__}: {exc}"})
    finally:
        db.close()

    if any(not s.get("passed", False) for s in steps):
        status = "FAIL"

    payload = {
        "status": status,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "mode": "simulated_notify",
        "note": "真實藍新 E2E 仍需 NEWEBPAY_* 商戶憑證",
        "steps": steps,
    }
    _write(payload)
    return 0 if status == "PASS" else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="CG-PAY NewebPay simulated E2E")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    code = run()
    if args.json:
        print(f"artifact={ARTIFACT}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())

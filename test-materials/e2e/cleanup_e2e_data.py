"""清除程式化 E2E 產生的殘留資料，讓真實測試從乾淨狀態開始。

清除：e2e 表單實例、e2e 審核請求、4 張訪談知識卡（含血緣/審查提醒）、
      5 個 demo 帳號的對話紀錄。
保留：入庫文件、場景註冊、版型、帳號、職能指派、非 e2e 的既有資料。

用法：cd Enclave && python test-materials/e2e/cleanup_e2e_data.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# 三輪 E2E 建立的表單實例（保留 9f9b154d：非本次 E2E 產生）
E2E_FORM_IDS = [
    "2bbffd3b-a30d-43a9-b774-c76cf3d41c78", "ffea55ad-fb45-4b2c-b5cb-9816612b484f",
    "b33f8ea6-47fc-4b02-99e5-22af3299c57f", "e3e98be0-1b7d-48e8-b8bf-c64950f40255",
    "4f1622a9-ad38-4a8e-af45-30847d1661be", "d0fd85c8-40d7-4803-bf9f-54edb920f5b4",
    "4fcbb0f0-e390-42e5-b655-f3b86a45f755", "1925e721-50f9-498c-aba1-ad1ae13f9a44",
    "a0256d7d-4c11-4087-a49d-8d6a60597d4e", "f6c3c05f-25bb-41f6-8c0d-17b5c24d83d4",
    "c6aead4c-69a8-4bae-aa7e-122bed3938ba", "a1e7f36d-7fc4-4e13-888e-2e50dc2febe7",
]
E2E_CARD_IDS = [
    "7a84dde3-2f9a-43a9-a4f2-b97c768a448d", "d438065b-7ce8-4361-97d3-d3d8a5a4a51e",
    "d6ad7725-f8e6-45cc-b553-8318e69f35cb", "c932eb61-deb3-4b58-a9a7-49df18d69d25",
]
DEMO_EMAILS = [
    "sales@demo.mka", "field@demo.mka", "master@demo.mka",
    "newcomer@demo.mka", "viewer@demo.mka",
]


def main() -> None:
    from app.db.session import SessionLocal
    from app.models.chat import Conversation, Message
    from app.models.mka import (
        FormInstance, KnowhowCardModel, KnowhowLineage,
        MKAApprovalRequest, MKAReviewReminder,
    )
    from app.models.user import User

    db = SessionLocal()
    try:
        # 1. e2e 審核請求（idempotency_key 以 e2e- 開頭）
        n_appr = db.query(MKAApprovalRequest).filter(
            MKAApprovalRequest.idempotency_key.like("e2e-%")
        ).delete(synchronize_session=False)
        print(f"approvals deleted: {n_appr}")

        # 2. e2e 表單實例
        n_forms = db.query(FormInstance).filter(
            FormInstance.id.in_(E2E_FORM_IDS)
        ).delete(synchronize_session=False)
        print(f"form instances deleted: {n_forms}")

        # 3. 知識卡的血緣與審查提醒
        n_lin = db.query(KnowhowLineage).filter(
            KnowhowLineage.card_id.in_(E2E_CARD_IDS)
        ).delete(synchronize_session=False)
        n_rem = db.query(MKAReviewReminder).filter(
            MKAReviewReminder.card_id.in_(E2E_CARD_IDS)
        ).delete(synchronize_session=False)
        print(f"lineage deleted: {n_lin}, reminders deleted: {n_rem}")

        # 4. e2e 知識卡
        n_cards = db.query(KnowhowCardModel).filter(
            KnowhowCardModel.id.in_(E2E_CARD_IDS)
        ).delete(synchronize_session=False)
        print(f"knowhow cards deleted: {n_cards}")

        # 5. demo 帳號的對話與訊息（messages 被 retrievaltraces 參照，須先清）
        from app.models.chat import RetrievalTrace

        demo_ids = [u.id for u in db.query(User).filter(User.email.in_(DEMO_EMAILS)).all()]
        conv_ids = [c.id for c in db.query(Conversation).filter(
            Conversation.user_id.in_(demo_ids)).all()]
        if conv_ids:
            msg_ids = [m.id for m in db.query(Message.id).filter(
                Message.conversation_id.in_(conv_ids)).all()]
            n_trace = db.query(RetrievalTrace).filter(
                RetrievalTrace.message_id.in_(msg_ids)).delete(
                synchronize_session=False) if msg_ids else 0
            n_msg = db.query(Message).filter(Message.conversation_id.in_(conv_ids)).delete(
                synchronize_session=False)
            n_conv = db.query(Conversation).filter(Conversation.id.in_(conv_ids)).delete(
                synchronize_session=False)
        else:
            n_trace = n_msg = n_conv = 0
        print(f"conversations deleted: {n_conv}, messages deleted: {n_msg}, traces deleted: {n_trace}")

        db.commit()

        # 驗證
        print("\n=== 驗證 ===")
        print("remaining form instances:", db.query(FormInstance).count())
        print("remaining knowhow cards:", db.query(KnowhowCardModel).count())
        print("remaining pending approvals:", db.query(MKAApprovalRequest).filter(
            MKAApprovalRequest.status == "pending").count())
        print("remaining demo-user conversations:", db.query(Conversation).filter(
            Conversation.user_id.in_(demo_ids)).count())
    finally:
        db.close()


if __name__ == "__main__":
    main()

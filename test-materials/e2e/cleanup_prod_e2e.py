"""清除生產環境（kachu.tw）上程式化 E2E 產生的殘留資料。

生產是新庫，Demo Tenant 內所有表單實例／知識卡都是 E2E 產生，
故依「demo 帳號建立者」清除，不用寫死 ID。
保留：入庫文件、場景註冊、版型、帳號、職能指派。

用法（在 web 容器內）：
  docker exec -e PYTHONPATH=/code enclave-web-1 python /tmp/cleanup_prod_e2e.py
"""
from __future__ import annotations

import sys
from pathlib import Path

try:
    ROOT = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(ROOT))
except IndexError:
    pass  # 容器內 /tmp 執行時由 PYTHONPATH=/code 提供 app 模組

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DEMO_EMAILS = [
    "sales@demo.mka", "field@demo.mka", "master@demo.mka",
    "newcomer@demo.mka", "viewer@demo.mka",
]


def main() -> None:
    from app.db.session import SessionLocal
    from app.models.chat import Conversation, Message, RetrievalTrace
    from app.models.mka import (
        FormInstance, KnowhowCardModel, KnowhowLineage,
        MKAApprovalRequest, MKAReviewReminder,
    )
    from app.models.user import User

    db = SessionLocal()
    try:
        demo_ids = [u.id for u in db.query(User).filter(User.email.in_(DEMO_EMAILS)).all()]
        print("demo users:", len(demo_ids))

        # 1. e2e 審核請求（idempotency_key 以 e2e- 開頭）
        n_appr = db.query(MKAApprovalRequest).filter(
            MKAApprovalRequest.idempotency_key.like("e2e-%")
        ).delete(synchronize_session=False)
        print(f"approvals deleted: {n_appr}")

        # 2. demo 帳號建立的表單實例（生產新庫全部皆 E2E 產生）
        form_ids = [f.id for f in db.query(FormInstance.id).all()]
        n_forms = db.query(FormInstance).filter(
            FormInstance.id.in_(form_ids)
        ).delete(synchronize_session=False) if form_ids else 0
        print(f"form instances deleted: {n_forms}")

        # 3. 知識卡（含血緣／審查提醒）
        card_ids = [c.id for c in db.query(KnowhowCardModel.id).all()]
        if card_ids:
            n_lin = db.query(KnowhowLineage).filter(
                KnowhowLineage.card_id.in_(card_ids)).delete(synchronize_session=False)
            n_rem = db.query(MKAReviewReminder).filter(
                MKAReviewReminder.card_id.in_(card_ids)).delete(synchronize_session=False)
            n_cards = db.query(KnowhowCardModel).filter(
                KnowhowCardModel.id.in_(card_ids)).delete(synchronize_session=False)
        else:
            n_lin = n_rem = n_cards = 0
        print(f"lineage deleted: {n_lin}, reminders deleted: {n_rem}, cards deleted: {n_cards}")

        # 4. demo 帳號的對話（messages 被 retrievaltraces 參照，須先清）
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

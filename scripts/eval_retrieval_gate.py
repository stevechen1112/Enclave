"""
評測閘門：Hit@K + ACL leakage = 0（真實 search 結果）。

用法：
  python scripts/eval_retrieval_gate.py

失敗條件（exit 1）：
  - ACL leakage > 0（受限主體 search 命中他部門文件）
  - Hit@5 低於基線（預設 0.6，可用 EVAL_HIT_AT_K_MIN 覆寫）

產物：artifacts/retrieval_gate_last_run.json
"""
from __future__ import annotations

import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
ARTIFACT = ROOT / "artifacts" / "retrieval_gate_last_run.json"

for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

os.environ.setdefault("POSTGRES_SERVER", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5435")

GOLDEN = [
    {"query": "品質管理", "must_contain_any": ["品質", "quality", "ISO"], "kb": None},
    {"query": "設備維護", "must_contain_any": ["維護", "maintenance", "油", "皮帶"], "kb": None},
    {"query": "安全程序", "must_contain_any": ["安全", "safety", "防護"], "kb": None},
]


def main() -> int:
    from app.db.session import SessionLocal
    from app.models.user import User
    from app.models.document import Document
    from app.core.authorization import AuthorizationContext
    from app.services.kb_retrieval import KnowledgeBaseRetriever

    db = SessionLocal()
    try:
        admin = db.query(User).filter(User.email.in_(["admin@example.com", "admin@enclave.local"])).first()
        if not admin:
            print("FAIL: no admin user for eval")
            return 1

        authz = AuthorizationContext.from_user(admin)
        retriever = KnowledgeBaseRetriever()
        hit_at_k = 0
        k = 5
        for case in GOLDEN:
            results = retriever.search(
                tenant_id=admin.tenant_id,
                query=case["query"],
                top_k=k,
                mode="hybrid",
                authz=authz,
                use_cache=False,
            )
            blob = " ".join((r.get("content") or "") for r in results).lower()
            ok = any(m.lower() in blob for m in case["must_contain_any"])
            print(f"Hit@5 '{case['query']}': {'PASS' if ok else 'MISS'} (n={len(results)})")
            if ok:
                hit_at_k += 1

        hit_rate = hit_at_k / max(1, len(GOLDEN))
        min_hit = float(os.getenv("EVAL_HIT_AT_K_MIN", "0.6"))
        print(f"Hit@5 rate={hit_rate:.2f} min={min_hit}")

        # ACL leakage：受限主體透過真實 search 不得命中他部門文件
        leakage = 0
        other_dept_docs = (
            db.query(Document)
            .filter(
                Document.tenant_id == admin.tenant_id,
                Document.tombstoned_at.is_(None),
                Document.department_id.isnot(None),
                Document.status == "completed",
            )
            .limit(20)
            .all()
        )
        restricted = AuthorizationContext(
            tenant_id=admin.tenant_id,
            subject_id=uuid.uuid4(),
            role_ids=["employee"],
            department_ids=[],
            is_superuser=False,
            policy_revision=authz.policy_revision + 1,
        )
        # predicate check
        for doc in other_dept_docs:
            if restricted.can_access_document(doc.tenant_id, doc.department_id):
                leakage += 1
                print(f"ACL LEAK(predicate): doc {doc.id} dept={doc.department_id}")

        # real search check
        if other_dept_docs:
            restricted_results = retriever.search(
                tenant_id=admin.tenant_id,
                query="品質 OR 安全 OR 維護 OR quality OR safety",
                top_k=20,
                mode="hybrid",
                authz=restricted,
                use_cache=False,
            )
            forbidden_ids = {str(d.id) for d in other_dept_docs}
            for r in restricted_results:
                if str(r.get("document_id")) in forbidden_ids:
                    leakage += 1
                    print(f"ACL LEAK(search): doc {r.get('document_id')}")

        print(f"ACL leakage count={leakage}")
        any_docs = db.query(Document).filter(Document.tenant_id == admin.tenant_id).count()
        status = "PASS"
        error = None
        if leakage > 0:
            status = "FAIL"
            error = "acl_leakage"
            print("GATE FAIL: ACL leakage > 0")
        elif hit_rate < min_hit and len(GOLDEN) > 0:
            if any_docs == 0:
                print("GATE WARN: empty KB — Hit@K skipped")
            else:
                status = "FAIL"
                error = "hit_at_k_below_baseline"
                print("GATE FAIL: Hit@K below baseline")
        else:
            print("GATE PASS")

        payload = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "status": status,
            "hit_rate": hit_rate,
            "hit_at_k_min": min_hit,
            "acl_leakage": leakage,
            "document_count": any_docs,
            "error": error,
        }
        ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
        ARTIFACT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return 0 if status == "PASS" else 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())

"""探測：C1 訪談卡片 vs D02 SOP 的衝突偵測是否會觸發。"""
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

from sqlalchemy import or_  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.models.document import Document, DocumentChunk  # noqa: E402
from app.services.sop_conflict import SOPConflictChecker  # noqa: E402

TENANT = "1da377f8-c66e-4df3-b0fb-8d9e2ee99c49"

db = SessionLocal()
try:
    # 1. 文件發現（套用修正後的邏輯）
    eq = "EQ-100-01"
    import re
    candidates = [eq]
    model = re.sub(r"-\d+$", "", eq)
    if model and model != eq:
        candidates.append(model)
    docs = (
        db.query(Document)
        .filter(
            Document.tenant_id == TENANT,
            or_(
                Document.filename.ilike("%SOP%"),
                Document.filename.ilike("%sop%"),
                Document.filename.ilike("%作業標準%"),
            ),
            or_(*[Document.filename.ilike(f"%{c}%") for c in candidates]),
        )
        .limit(10)
        .all()
    )
    print("SOP docs found:", [d.filename for d in docs])

    # 2. 建立 sop_docs（同 _run_sop_conflict_check）
    sop_docs = []
    for doc in docs:
        chunks = (
            db.query(DocumentChunk)
            .filter(DocumentChunk.document_id == doc.id, DocumentChunk.tenant_id == TENANT)
            .order_by(DocumentChunk.chunk_index.asc())
            .limit(40)
            .all()
        )
        texts = [c.text or "" for c in chunks if c.text]
        steps = [t for t in texts if any(k in t for k in ("步驟", "1.", "2.", "操作"))]
        cautions = [t for t in texts if any(k in t for k in ("注意", "禁止", "危險", "安全"))]
        sop_docs.append({
            "id": str(doc.id), "title": doc.filename,
            "steps": steps or texts[:5],
            "applicable_equipment": ["EQ-100-01"],
            "cautions": cautions,
        })
        print(f"  {doc.filename}: chunks={len(texts)} steps={len(steps)} cautions={len(cautions)}")

    # 3. 模擬訪談卡片（用 C1 逐字稿的提取結果）
    class FakeCard:
        steps = [
            "張力異常時先聽放捲軸的聲音判斷鬆緊",
            "用目測和手感調整磁粉離合器電流",
            "E-07 跳機時按復歸鍵繼續跑，連跳三次再停機",
        ]
        equipment_ids = ["EQ-100-01"]
        cautions = ["老機台聽聲音比張力計快"]

    checker = SOPConflictChecker()
    all_texts = []
    for s in sop_docs:
        all_texts.extend(s["steps"] + s["cautions"])
    terms = checker._extract_prohibited_terms(all_texts)

    conflicts = checker.check_conflicts(FakeCard(), sop_docs)

    import json
    out = {
        "terms": sorted(terms.keys()),
        "conflict_count": len(conflicts),
        "conflicts": [
            {"term_src": c.sop_value, "card": c.knowhow_value, "desc": c.description}
            for c in conflicts
        ],
    }
    (Path(__file__).parent / "_probe_out.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print("written _probe_out.json; conflicts:", len(conflicts))
    for c in conflicts[:5]:
        print(f"  [{c.conflict_type}] {c.description}")
        print(f"    SOP: {c.sop_value[:80]}")
        print(f"    KH : {c.knowhow_value[:80]}")
finally:
    db.close()

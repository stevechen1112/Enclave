"""Annotate Blind Z4 GT from ingested DB chunk text only.

No Enclave chat. Spans must appear in artifacts/blind_z4/ingested_text/.
"""
from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
INTENT = ROOT / "artifacts" / "blind_z4" / "intent_questions_draft_v1.yaml"
OUT = ROOT / "testdata" / "golden" / "z4_blind_questions.yaml"
META_OUT = ROOT / "artifacts" / "blind_z4" / "gt_annotation_log.yaml"

ROLE = {"A": "legal", "B": "owner", "C": "finance", "D": "legal", "E": "legal"}

# GT from ingested_text (export_blind_z4_ingested.py). refuse → must_refuse.
GT: dict[str, dict] = {
    # A
    "z4-i-001": {"spans": ["臺鍍", "姚建宇"], "notes": "doc-03 標的臺鍍；乙方姚建宇"},
    "z4-i-002": {"spans": ["社群媒體", "亞馬遜"], "notes": "doc-09 服務項目"},
    "z4-i-003": {"spans": ["奕瑞科技", "八策品牌"], "notes": "doc-37 雙方"},
    "z4-i-004": {"spans": ["生酮飲食", "40,000"], "notes": "doc-36 標的+總計"},
    "z4-i-005": {"spans": ["70,000", "鴻鼎菓子"], "notes": "doc-40 未稅柒萬"},
    "z4-i-006": {"spans": ["27,000", "28,350"], "notes": "doc-38 未稅/含稅"},
    "z4-i-007": {"spans": ["38,000", "35,000"], "notes": "doc-15 建置+月費"},
    "z4-i-008": {"spans": ["18,900"], "notes": "doc-39 含稅總計"},
    "z4-i-009": {"spans": ["45,000"], "notes": "doc-27 電商方案月費"},
    "z4-i-010": {"spans": ["25,000", "立壕"], "notes": "doc-35 請款"},
    "z4-i-011": {"spans": ["八策品牌", "20,000"], "notes": "doc-25 甲方+月酬"},
    "z4-i-012": {"spans": ["電子發票", "字軌"], "notes": "doc-26 申請標的"},
    # B
    "z4-i-013": {"spans": ["30,000", "優克美"], "notes": "doc-01 投放操作費月"},
    "z4-i-014": {"spans": ["20,000", "SEO"], "notes": "doc-02"},
    "z4-i-015": {"spans": ["40,000"], "notes": "doc-04 總計；入庫正文為健身俱樂部報價"},
    "z4-i-016": {"spans": ["CYS假髮", "SEO"], "notes": "doc-05 標的項目"},
    "z4-i-017": {"spans": ["115,500", "110,000"], "notes": "doc-06 含稅/未稅"},
    "z4-i-018": {"spans": ["250,000"], "notes": "doc-07"},
    "z4-i-019": {"spans": ["120,000", "瑪格麗特"], "notes": "doc-08"},
    "z4-i-020": {"spans": ["987", "康宇"], "notes": "doc-10 含稅金額"},
    "z4-i-021": {"spans": ["147,000", "140,000"], "notes": "doc-11"},
    "z4-i-022": {"spans": ["10,000", "綠界"], "notes": "doc-12 年服務費"},
    "z4-i-023": {"spans": ["180,000", "1028"], "notes": "doc-13 KOL 價"},
    "z4-i-024": {"spans": ["72,000"], "notes": "doc-14 總價"},
    "z4-i-025": {"spans": ["50,000", "30,000"], "notes": "doc-16 月費區間"},
    "z4-i-026": {"spans": ["35,700", "34,000"], "notes": "doc-17"},
    "z4-i-027": {"spans": ["240,000", "光昱金屬"], "notes": "doc-18"},
    "z4-i-028": {"spans": ["34,000", "65,000"], "notes": "doc-28 電商方案/網站"},
    # C
    "z4-i-029": {"spans": ["Labavo", "SEO"], "notes": "doc-01 vs doc-02"},
    "z4-i-030": {"spans": ["35,700", "115,500"], "notes": "doc-17 vs doc-06 金額不同"},
    "z4-i-031": {"spans": ["假髮", "新聞"], "notes": "doc-05 vs doc-11"},
    "z4-i-032": {"spans": ["40,000", "JSwedding"], "notes": "合約金額 vs 提案檔名"},
    "z4-i-033": {"spans": ["120,000", "創新模式"], "notes": "執行案合約 vs 提案"},
    "z4-i-034": {"spans": ["名片", "綠界"], "notes": "印刷 vs 金流；綠界較像金流非行銷服務"},
    "z4-i-035": {"spans": ["38,000", "28,350", "18,900"], "notes": "街道/樂行家/谷德"},
    "z4-i-036": {"spans": ["捷豹", "奕瑞"], "notes": "doc-09 甲方捷豹；doc-37 奕瑞"},
    "z4-i-037": {"spans": ["宏茂", "優克美", "奕瑞"], "notes": "檔名含報價合約之客戶"},
    "z4-i-038": {"spans": ["72,000", "提案"], "notes": "報價單 vs 行銷整合提案"},
    # D refuse
    "z4-i-039": {"refuse": True, "notes": "幽靈客戶心恬"},
    "z4-i-040": {"refuse": True, "notes": "未上傳 SECRET2028"},
    "z4-i-041": {"refuse": True, "notes": "杏壺無量產上線保證日"},
    "z4-i-042": {"refuse": True, "notes": "工作委託無技術股"},
    "z4-i-043": {"refuse": True, "notes": "字軌申請書無銀行密碼"},
    "z4-i-044": {"refuse": True, "notes": "請款單無入帳保證日"},
    # E
    "z4-i-045": {"spans": ["20190628", "10份", "Emma"], "notes": "三檔檔名分列"},
    "z4-i-046": {"spans": ["35,700", "115,500"], "notes": "非同一複本"},
    "z4-i-047": {"spans": ["光昱金屬", "瑪謝"], "notes": "catalog 路徑；入庫檔名光昱金屬"},
    "z4-i-048": {"spans": ["JSwedding", "健身"], "notes": "不同提案"},
    "z4-i-049": {"spans": ["Dr. Kelly", "Color Hair"], "notes": "分檔"},
    "z4-i-050": {"spans": ["味特", "鴻鼎"], "notes": "不同客戶"},
}


def main() -> None:
    intent = yaml.safe_load(INTENT.read_text(encoding="utf-8"))
    missing = [q["id"] for q in intent["questions"] if q["id"] not in GT]
    if missing:
        raise SystemExit(f"missing GT for: {missing}")

    # Verify spans appear in at least one ingested file (or refuse)
    texts = []
    for p in (ROOT / "artifacts" / "blind_z4" / "ingested_text").glob("*.txt"):
        texts.append(p.read_text(encoding="utf-8"))
    blob = "\n".join(texts)

    questions = []
    log = []
    for q in intent["questions"]:
        g = GT[q["id"]]
        if g.get("refuse"):
            exp: dict = {"document_ids": [], "must_refuse": True}
        else:
            spans = g["spans"]
            missing_spans = [s for s in spans if s not in blob]
            if missing_spans:
                # soft warn — 瑪謝 may only be in catalog path not chunks
                print(f"WARN {q['id']} spans not in ingested blob: {missing_spans}")
            exp = {"span_contains": spans}
        questions.append(
            {
                "id": q["id"],
                "category": f"blind_z4_{q['type']}",
                "type": q["type"],
                "role": ROLE[q["type"]],
                "query": q["query"],
                "expected": exp,
                "evidence_hint": q.get("catalog_hint"),
            }
        )
        log.append({"id": q["id"], "notes": g.get("notes", ""), "refuse": bool(exp.get("must_refuse"))})

    # Fix soft failures that are path-only
    for q in questions:
        if q["id"] == "z4-i-047" and "瑪謝" in (q["expected"].get("span_contains") or []):
            # ingested text may not contain folder name; use filename-only spans
            q["expected"]["span_contains"] = ["光昱金屬"]
            for row in log:
                if row["id"] == "z4-i-047":
                    row["notes"] += "；瑪謝僅在 catalog 路徑，GT 改用檔內光昱金屬"

    payload = {
        "version": "4.0-blind-dual-root",
        "meta": {
            "intent_frozen": True,
            "gt_frozen": True,
            "gt_frozen_at": "2026-08-05",
            "source_roots": [
                r"C:\Users\User\Desktop\八策",
                r"C:\Users\User\Desktop\客戶",
            ],
            "corpus": "artifacts/blind_z4/corpus_manifest.json",
            "ingested_text": "artifacts/blind_z4/ingested_text/",
            "anti_target_drawing": True,
            "note": (
                "GT from ingested DB chunks only (export_blind_z4_ingested.py). "
                "No Enclave chat during annotation. Intent frozen before upload."
            ),
        },
        "questions": questions,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    hdr = (
        "# Blind Z4 — GT FROZEN (dual-root 八策+客戶)\n"
        "# Do not edit question stems. Errata only via gt_errata.\n"
        "# Spans validated against artifacts/blind_z4/ingested_text/\n\n"
    )
    OUT.write_text(
        hdr + yaml.safe_dump(payload, allow_unicode=True, sort_keys=False, width=100),
        encoding="utf-8",
    )
    META_OUT.write_text(
        yaml.safe_dump({"annotations": log}, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    n = len(questions)
    refuse = sum(1 for q in questions if q["expected"].get("must_refuse"))
    print(f"WROTE {OUT} n={n} refuse={refuse} answerable={n - refuse}")


if __name__ == "__main__":
    main()

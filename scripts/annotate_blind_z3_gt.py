"""Annotate Blind Z3 GT from independent extracts + visual reads of scans.

Does NOT call Enclave chat. Outputs testdata/golden/z3_blind_questions.yaml
in eval_answer_correctness format.
"""
from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
INTENT = ROOT / "artifacts" / "blind_z3" / "intent_questions_draft_v3.yaml"
OUT = ROOT / "testdata" / "golden" / "z3_blind_questions.yaml"
META_OUT = ROOT / "artifacts" / "blind_z3" / "gt_annotation_log.yaml"

# GT keyed by question id. Source: original extract text or page_previews visual read.
# refuse=True → must_refuse. spans = span_contains list.
GT: dict[str, dict] = {
    # 優利
    # 優利（visual）
    "z3-v3-001": {"spans": ["0531", "已填"], "notes": "D01/D02 檔名差異"},
    "z3-v3-002": {"spans": ["20,000"], "notes": "D01 月酬未稅"},
    "z3-v3-003": {"spans": ["優利資源整合", "八策數位"], "notes": "D01 雙方"},
    # 宏寰
    "z3-v3-004": {"spans": ["亞馬遜", "8月31"], "notes": "D03 服務至8/31；金額首頁未列則期間+標的可核"},
    "z3-v3-005": {"spans": ["亞馬遜", "SEO"], "notes": "兩約標的不同"},
    "z3-v3-006": {"spans": ["宏寰貿易", "八策品牌"], "notes": "D05"},
    "z3-v3-007": {"spans": ["優克美"], "notes": "D04 抬頭可核；全文弱"},
    # 安可
    "z3-v3-008": {"spans": ["安可日子", "八策品牌"], "notes": "D06"},
    "z3-v3-009": {"spans": ["696,500"], "notes": "D14 第一期調整後總計"},
    "z3-v3-010": {"spans": ["委託合約", "報價"], "notes": "不同文件"},
    "z3-v3-011": {"spans": ["第一期", "第二期"], "notes": "D14 分期結構"},
    "z3-v3-012": {"spans": ["訂金"], "notes": "應說明缺訂金比例；答「未載明訂金」可含訂金二字"},
    # 地政
    "z3-v3-013": {"spans": ["18,000"], "notes": "D07"},
    "z3-v3-014": {"spans": ["18,000", "60,000"], "notes": "合約 vs 網站報價"},
    "z3-v3-015": {"spans": ["60,000"], "notes": "D23 網站建置"},
    # 味特 貝昇 樂行家
    "z3-v3-016": {"spans": ["350,000"], "notes": "D08"},
    "z3-v3-017": {"spans": ["60,000"], "notes": "D10"},
    "z3-v3-018": {"spans": ["樂行象", "八策品牌"], "notes": "D09 手寫甲方"},
    "z3-v3-019": {"spans": ["20,000"], "notes": "D11 SEO月費"},
    # 光昱
    "z3-v3-020": {"refuse": True, "notes": "D15/D16 無總價"},
    "z3-v3-021": {"spans": ["21,500"], "notes": "D12"},
    "z3-v3-022": {"spans": ["3D", "亞馬遜"], "notes": "標的不同"},
    # 巽耘 醫美 瑪格麗特
    "z3-v3-023": {"spans": ["87,000"], "notes": "D17"},
    "z3-v3-024": {"spans": ["15,000"], "notes": "D18 數據分析月費（代表金額）"},
    "z3-v3-025": {"refuse": True, "notes": "D19 無總價"},
    "z3-v3-026": {"spans": ["0219", "建議"], "notes": "兩檔用途不同"},
    "z3-v3-027": {"refuse": True, "notes": "D21 無總價"},
    "z3-v3-028": {"spans": ["35,000"], "notes": "D22 方案A專訪"},
    "z3-v3-029": {"spans": ["11,550"], "notes": "D24"},
    # 提案
    "z3-v3-030": {"spans": ["Yumi"], "notes": "近複本分檔"},
    "z3-v3-031": {"spans": ["包裝"], "notes": "D27"},
    "z3-v3-032": {"spans": ["生酮"], "notes": "D28"},
    "z3-v3-033": {"refuse": True, "notes": "D31 掃描未可靠全文"},
    "z3-v3-034": {"spans": ["貼文"], "notes": "CYS粉專提案"},
    "z3-v3-035": {"refuse": True, "notes": "D30 掃描未全文視讀"},
    # 八策內部
    "z3-v3-036": {"spans": ["2,630"], "notes": "D33 Regus月租優惠價"},
    "z3-v3-037": {"spans": ["19,425"], "notes": "D34 月租金"},
    "z3-v3-038": {"spans": ["Regus", "巴菲特"], "notes": "不同出租方"},
    "z3-v3-039": {"spans": ["米克", "創騰"], "notes": "兩委託對象"},
    "z3-v3-040": {"spans": ["196,000"], "notes": "D35"},
    "z3-v3-041": {"spans": ["創騰"], "notes": "檔名/對象"},
    "z3-v3-042": {"spans": ["發票"], "notes": "委任書標的"},
    "z3-v3-043": {"refuse": True, "notes": "D37 未可靠視讀"},
    # gov
    "z3-v3-044": {"spans": ["Joyshot"], "notes": "D39"},
    "z3-v3-045": {"refuse": True, "notes": "D40 掃描"},
    "z3-v3-046": {"refuse": True, "notes": "D41 掃描"},
    "z3-v3-047": {"spans": ["綠界"], "notes": "D42"},
    "z3-v3-048": {"spans": ["捷報"], "notes": "兩檔近名；答應分檔"},
    "z3-v3-049": {"refuse": True, "notes": "D43 無總價"},
    "z3-v3-050": {"spans": ["BravoMix"], "notes": "D45"},
    "z3-v3-051": {"spans": ["勞資會議"], "notes": "D46"},
    "z3-v3-052": {"spans": ["宏茂"], "notes": "D47"},
    "z3-v3-053": {"spans": ["Dapro"], "notes": "D48"},
    "z3-v3-054": {"spans": ["瑪謝"], "notes": "D49"},
    "z3-v3-055": {"spans": ["Color"], "notes": "D50"},
    "z3-v3-056": {"spans": ["街道沙龍"], "notes": "D51"},
    "z3-v3-057": {"spans": ["台鍍"], "notes": "D52"},
    "z3-v3-058": {"refuse": True, "notes": "D53 無總價"},
    "z3-v3-059": {"spans": ["115,500"], "notes": "D54 含稅總金額"},
    "z3-v3-060": {"spans": ["696,225"], "notes": "D55"},
    # 跨檔
    "z3-v3-061": {"spans": ["87,000", "11,550"], "notes": "巽耘>立壕；醫美口徑另述"},
    "z3-v3-062": {"spans": ["696,500", "350,000"], "notes": "安可調整後 vs 味特"},
    "z3-v3-063": {"spans": ["提案", "合約"], "notes": "類型差"},
    "z3-v3-064": {"spans": ["安可日子", "Regus"], "notes": "不同文件"},
    "z3-v3-065": {"spans": ["60,000", "11,550"], "notes": "地政>立壕"},
    "z3-v3-066": {"spans": ["Color", "街道沙龍"], "notes": "不同客戶"},
    "z3-v3-067": {"spans": ["安可", "醫美圈圈"], "notes": "含八策相關"},
    "z3-v3-068": {"refuse": True, "notes": "捷報缺總價無法比"},
    "z3-v3-069": {"spans": ["RFQ", "立壕"], "notes": "教材vs報價"},
    "z3-v3-070": {"spans": ["Color", "街道沙龍"], "notes": "行銷提案客戶"},
    # 拒答
    "z3-v3-071": {"refuse": True, "notes": "幽靈客戶"},
    "z3-v3-072": {"refuse": True, "notes": "無年利率"},
    "z3-v3-073": {"refuse": True, "notes": "無上線日保證"},
    "z3-v3-074": {"refuse": True, "notes": "無技術股"},
    "z3-v3-075": {"refuse": True, "notes": "無載具"},
    "z3-v3-076": {"refuse": True, "notes": "無該檔名"},
    "z3-v3-077": {"refuse": True, "notes": "未選心恬"},
    "z3-v3-078": {"refuse": True, "notes": "無營收保證％"},
    # 補
    "z3-v3-079": {"spans": ["RFQ"], "notes": "D13"},
    "z3-v3-080": {"refuse": True, "notes": "D20 無總價"},
    "z3-v3-081": {"spans": ["台北地方法院"], "notes": "D06"},
    "z3-v3-082": {"spans": ["EncoreWeb"], "notes": "D14"},
    "z3-v3-083": {"spans": ["優克美"], "notes": "D11 即優克美SEO"},
    "z3-v3-084": {"spans": ["60,000", "350,000"], "notes": "貝昇vs味特"},
    "z3-v3-085": {"spans": ["捷報", "立壕"], "notes": "兩側文件"},
}


def main() -> None:
    intent = yaml.safe_load(INTENT.read_text(encoding="utf-8"))
    missing = [q["id"] for q in intent["questions"] if q["id"] not in GT]
    if missing:
        raise SystemExit(f"missing GT for: {missing}")

    questions = []
    log = []
    for q in intent["questions"]:
        g = GT[q["id"]]
        exp: dict = {}
        if g.get("refuse") or q.get("must_refuse"):
            exp = {"document_ids": [], "must_refuse": True}
        else:
            exp = {"span_contains": g["spans"]}
        questions.append(
            {
                "id": q["id"],
                "category": f"blind_z3_{q['type']}",
                "type": q["type"],
                "role": q["role"],
                "query": q["question"],
                "expected": exp,
                "evidence_hint": q.get("evidence_hint"),
            }
        )
        log.append({"id": q["id"], "notes": g.get("notes", ""), "refuse": bool(exp.get("must_refuse"))})

    payload = {
        "version": "3.0-blind-dual-root",
        "meta": {
            "intent_frozen": True,
            "gt_frozen": True,
            "gt_frozen_at": "2026-08-05",
            "source_roots": [
                r"C:\Users\User\Desktop\八策",
                r"C:\Users\User\Desktop\客戶",
            ],
            "corpus": "artifacts/blind_z3/corpus_manifest.json",
            "anti_target_drawing": True,
            "note": (
                "GT from independent pdfplumber/docx extracts + visual read of scans. "
                "No Enclave chat used during annotation. "
                "Some scan/proposal items marked must_refuse when amount/detail not verifiable."
            ),
        },
        "questions": questions,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    hdr = (
        "# Blind Z3 — GT FROZEN (dual-root 八策+客戶)\n"
        "# Do not edit question stems. Errata only via gt_errata.\n\n"
    )
    OUT.write_text(hdr + yaml.safe_dump(payload, allow_unicode=True, sort_keys=False, width=100), encoding="utf-8")
    META_OUT.write_text(yaml.safe_dump({"annotations": log}, allow_unicode=True, sort_keys=False), encoding="utf-8")

    n = len(questions)
    refuse = sum(1 for q in questions if q["expected"].get("must_refuse"))
    print(f"WROTE {OUT} n={n} refuse={refuse} answerable={n-refuse}")
    print(f"WROTE {META_OUT}")


if __name__ == "__main__":
    main()

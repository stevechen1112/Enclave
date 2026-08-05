"""從 z1_scan_annotations 自動展開欄位題，湊齊黃金集規模（VISION Phase 4）。

產出 testdata/golden/z1_expanded_from_annotations.yaml（可與主集合併評測）。

一致性自檢（防止錯標註污染題庫）：
- 每個欄位的驗證值（span > ocr_surface > expected）必須能在該文件的
  DB OCR 全文（documentchunks）中找到（NFKC + casefold + 去空白/標點）。
- 找不到且未標 `allow_absent: true` 的欄位：不產題、列入
  artifacts/golden_annotation_selfcheck.json，並以非零碼結束（閘門）。
- `allow_absent: true` 僅用於由編譯層（clause projection）回答、
  不存在於 OCR 字面的欄位（如 ETI 英譯對照）。
"""
from __future__ import annotations

import json
import os
import pathlib
import unicodedata

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
ANN = ROOT / "testdata" / "golden" / "z1_scan_annotations"
OUT = ROOT / "testdata" / "golden" / "z1_expanded_from_annotations.yaml"
REPORT = ROOT / "artifacts" / "golden_annotation_selfcheck.json"

_STRIP_CHARS = "-–—_:：/()（）"


def _norm(s: object) -> str:
    s = unicodedata.normalize("NFKC", str(s)).casefold()
    return "".join(ch for ch in s if not ch.isspace() and ch not in _STRIP_CHARS)


def _load_ocr_texts() -> dict[str, str]:
    """filename -> concatenated chunk text（從 DB 取實際 OCR 全文）。"""
    from sqlalchemy import create_engine, text

    eng = create_engine(
        "postgresql+psycopg2://%s:%s@%s:%s/%s"
        % (
            os.environ.get("POSTGRES_USER", "postgres"),
            os.environ.get("POSTGRES_PASSWORD", "postgres"),
            os.environ.get("POSTGRES_SERVER", "localhost"),
            os.environ.get("POSTGRES_PORT", "5435"),
            os.environ.get("POSTGRES_DB", "enclave"),
        )
    )
    texts: dict[str, list[str]] = {}
    with eng.connect() as c:
        rows = c.execute(
            text(
                "SELECT d.filename, c.text FROM documents d "
                "JOIN documentchunks c ON c.document_id=d.id"
            )
        ).fetchall()
        for fn, tx in rows:
            if tx:
                texts.setdefault(fn, []).append(tx)
    return {fn: "\n".join(parts) for fn, parts in texts.items()}


def main() -> int:
    ocr_texts = _load_ocr_texts()
    questions = []
    violations = []
    allowed_absent = []
    n = 0
    for path in sorted(ANN.glob("scan_*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        sid = data["id"]
        filename = data.get("filename") or sid
        doc_text = _norm(ocr_texts.get(filename, ""))
        for field in data.get("fields") or []:
            name = field.get("name") or "field"
            expected = str(field.get("expected") or "").strip()
            if not expected or len(expected) < 2:
                continue
            span = str(field.get("span") or expected).strip()
            verify_value = field.get("span") or field.get("ocr_surface") or expected
            found = _norm(verify_value) in doc_text
            if not found:
                entry = {"scan": sid, "filename": filename, "field": name,
                         "expected": expected, "verify_value": str(verify_value)}
                if field.get("allow_absent"):
                    allowed_absent.append(entry)
                else:
                    violations.append(entry)
                    continue
            n += 1
            qid = f"E{n:03d}"
            label = str(field.get("label") or "").strip()
            if label:
                query = f"根據文件《{filename}》，{label}是什麼？"
            else:
                query = f"根據文件《{filename}》，欄位「{name}」的值是什麼？"
            questions.append({
                "id": qid,
                "category": "annotation_field",
                "query": query,
                "expected": {
                    "document_ids": [sid],
                    "span_contains": [span],
                },
            })
    doc = {
        "version": 2,
        "gate": "Z1-EXPANDED",
        "status": "GENERATED",
        "source": "z1_scan_annotations",
        "selfcheck": "expected values verified against DB OCR text",
        "questions": questions,
    }
    OUT.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")
    REPORT.parent.mkdir(exist_ok=True)
    REPORT.write_text(
        json.dumps({"violations": violations, "allowed_absent": allowed_absent},
                   ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    print(f"wrote {len(questions)} questions → {OUT}")
    print(f"selfcheck: {len(violations)} violations, {len(allowed_absent)} allow_absent → {REPORT}")
    if violations:
        for v in violations:
            print(f"  VIOLATION {v['scan']}.{v['field']}: {v['expected']!r} not in OCR text")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

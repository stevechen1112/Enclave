"""Build annotation workbook: question + independent extract snippets (for GT only)."""
from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

OUT = Path(__file__).resolve().parents[1] / "artifacts" / "blind_z3"
INTENT = OUT / "intent_questions_draft_v3.yaml"
IDX = OUT / "extract_index.json"


def main() -> None:
    intent = yaml.safe_load(INTENT.read_text(encoding="utf-8"))
    idx = {e["id"]: e for e in json.loads(IDX.read_text(encoding="utf-8"))}
    # also map doc-XX -> DXX
    lines = ["# GT annotation workbook — from independent extracts / preview paths\n"]
    for q in intent["questions"]:
        qid = q["id"]
        hint = str(q.get("evidence_hint", ""))
        doc_ids = re.findall(r"doc-(\d+)", hint)
        lines.append(f"\n## {qid} [{q['type']}/{q['answer_shape']}] refuse={q.get('must_refuse')}")
        lines.append(f"Q: {q['question']}")
        lines.append(f"hint: {hint}")
        for d in doc_ids:
            did = f"D{int(d):02d}"
            e = idx.get(did)
            if not e:
                lines.append(f"- {did}: MISSING")
                continue
            ext_path = Path(e["extract"])
            text = ext_path.read_text(encoding="utf-8", errors="ignore") if ext_path.exists() else ""
            lines.append(f"- {did} {e['name']} chars={e['chars']}")
            if e["chars"] == 0:
                prev = OUT / "page_previews" / f"{did}_p1.png"
                lines.append(f"  PREVIEW: {prev}")
            else:
                snippet = re.sub(r"\s+", " ", text)[:1800]
                lines.append(f"  TEXT: {snippet}")
    out = OUT / "annotation_workbook.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print("WROTE", out, "bytes", out.stat().st_size)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Verify Phase 1 test data set and compute hashes for consistency checks."""
from pathlib import Path
import hashlib

DOCS_DIR = Path(__file__).resolve().parent.parent / "test-data" / "company-documents"

FILES = [
    ("hr-regulations", "員工手冊-第一章-總則.pdf"),
    ("hr-regulations", "獎懲管理辦法.pdf"),
    ("sop", "新人到職SOP.pdf"),
    ("sop", "報帳作業規範.pdf"),
    ("employee-data", "員工名冊.csv"),
    ("payroll", "202601-E007-劉志明-薪資條.pdf"),
    ("forms", "請假單範本-E012-周秀蘭.pdf"),
    ("contracts", "勞動契約書-謝雅玲.pdf"),
    ("health-records", "健康檢查報告-E016-高淑珍.pdf"),
    ("official-forms", "變更登記表A.jpg"),
    ("official-forms", "變更登記表B.jpg"),
]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


ok = 0
print(f"Docs root: {DOCS_DIR}")
for folder, name in FILES:
    path = DOCS_DIR / folder / name
    if path.exists():
        ok += 1
        size = path.stat().st_size
        digest = sha256(path)
        print(f"OK  {folder}/{name} | {size} bytes | {digest}")
    else:
        print(f"MISSING  {folder}/{name}")

print(f"\nSummary: {ok}/{len(FILES)} files present")

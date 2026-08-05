"""Verify cloud plan fixes landed correctly."""
import io
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
text = Path("docs/CLOUD_AND_COMMERCIALIZATION_PLAN.md").read_text(encoding="utf-8")

checks = [
    ("Luna／Voyage／選配 OCR；Sol 已退場", True),
    ("LLM API（Luna）", True),
    ("COGS 失控（LLM＋OCR＋rerank）", True),
    ("`tests/load/`", True),
    ("4 美元/千頁", True),
    ("4,000 美元", True),
    ("廉價內部模型", True),
    ("與 fleet 監控", True),
    ("D7", True),
    ("Voyage embed＋雲端小模型稽核", True),
    ("Embedding（bge-m3）", True),
    ("\t", False),
    ("gpt-5.6-sol", False),  # 只剩消融歷史表格裡的合法引用
]
ok = True
for s, expected in checks:
    got = s in text
    status = "OK  " if got == expected else "FAIL"
    if got != expected:
        ok = False
    print(status, repr(s[:36]), "->", got)

# sol 殘留位置（應只在消融歷史表）
for i, line in enumerate(text.splitlines(), 1):
    if "sol" in line.lower() and "5.6-sol" in line.lower():
        print(f"  sol ref line {i}: {line[:80]}")

print("ALL OK" if ok else "HAS FAILURES")

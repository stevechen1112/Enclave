"""Markdown → 排版 HTML，供 headless Chrome 列印 PDF。

用法：python _md_to_pdf.py <input.md> <output.html>
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import markdown

CSS = """
@page { size: A4; margin: 18mm 16mm; }
* { box-sizing: border-box; }
body {
  font-family: "Microsoft JhengHei", "微軟正黑體", "Noto Sans CJK TC", sans-serif;
  font-size: 10.5pt; line-height: 1.65; color: #1a1a1a; margin: 0;
}
h1 { font-size: 20pt; border-bottom: 3px solid #2563eb; padding-bottom: 8px;
     margin: 0 0 18px; color: #1e3a8a; }
h2 { font-size: 15pt; border-left: 5px solid #2563eb; padding-left: 10px;
     margin: 28px 0 12px; color: #1e3a8a; page-break-after: avoid; }
h3 { font-size: 12.5pt; margin: 20px 0 8px; color: #1f2937; page-break-after: avoid; }
h4 { font-size: 11pt; margin: 16px 0 6px; color: #374151; page-break-after: avoid; }
p { margin: 6px 0; }
table { border-collapse: collapse; width: 100%; margin: 10px 0; font-size: 9.5pt; }
th, td { border: 1px solid #cbd5e1; padding: 5px 8px; text-align: left;
         vertical-align: top; }
th { background: #eff6ff; font-weight: 600; }
tr { page-break-inside: avoid; }
code { font-family: Consolas, "Courier New", monospace; font-size: 9pt;
       background: #f1f5f9; padding: 1px 5px; border-radius: 3px; }
pre { background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 6px;
      padding: 10px 12px; overflow-x: auto; page-break-inside: avoid; }
pre code { background: none; padding: 0; }
blockquote { border-left: 4px solid #fbbf24; background: #fffbeb;
             margin: 10px 0; padding: 8px 14px; color: #78350f; }
ul, ol { margin: 6px 0; padding-left: 24px; }
li { margin: 3px 0; }
hr { border: none; border-top: 1px solid #e2e8f0; margin: 20px 0; }
a { color: #2563eb; text-decoration: none; }
strong { color: #111827; }
"""


def main() -> None:
    src, dst = Path(sys.argv[1]), Path(sys.argv[2])
    text = src.read_text(encoding="utf-8")
    # 移除文件開頭的 YAML front matter（若有）
    text = re.sub(r"\A---\n.*?\n---\n", "", text, flags=re.S)
    body = markdown.markdown(
        text, extensions=["tables", "fenced_code", "toc", "nl2br"]
    )
    html = (
        "<!DOCTYPE html><html lang='zh-Hant'><head><meta charset='utf-8'>"
        f"<title>{src.stem}</title><style>{CSS}</style></head>"
        f"<body>{body}</body></html>"
    )
    dst.write_text(html, encoding="utf-8")
    print(f"html: {dst}")


if __name__ == "__main__":
    main()

"""
將測試資料中的 TXT / MD / CSV 文件轉換為 PDF 格式
支援中文字元（微軟正黑體）、自動截斷超寬裝飾線
"""

from fpdf import FPDF
import csv
import os
import re
from pathlib import Path


class ChinesePDF(FPDF):
    """支援中文的 PDF"""

    def __init__(self, orientation='P'):
        super().__init__(orientation=orientation, format='A4')
        self.set_auto_page_break(auto=True, margin=15)

        font_candidates = [
            (r"C:\Windows\Fonts\msjh.ttc", "msjh"),
            (r"C:\Windows\Fonts\kaiu.ttf", "kaiu"),
            (r"C:\Windows\Fonts\msyh.ttc", "msyh"),
        ]

        self._font_name = 'Helvetica'
        for fpath, fname in font_candidates:
            if os.path.exists(fpath):
                try:
                    self.add_font(fname, '', fpath)
                    self._font_name = fname
                    break
                except Exception:
                    continue

    def body_font(self, size=9):
        self.set_font(self._font_name, '', size)

    def footer(self):
        self.set_y(-15)
        self.body_font(7)
        self.set_text_color(150, 150, 150)
        self.cell(0, 10, f'- {self.page_no()} -', align='C')
        self.set_text_color(0, 0, 0)


# ── 裝飾線截斷 ──────────────────────────────

DECO_CHARS = set('═─━┅┄┈┉╌╍▬▭☐☑✅✓✗│┃┆┇┊┋╰╯╭╮├┤┬┴┼╋')


def shorten_deco(line, max_len=68):
    """若整行 >80% 為裝飾字元，截短到 max_len"""
    s = line.rstrip()
    if len(s) < 5:
        return line
    ratio = sum(1 for c in s if c in DECO_CHARS) / len(s)
    if ratio > 0.75:
        ch = s[0]
        return ch * min(len(s), max_len)
    return line


# ── TXT → PDF ────────────────────────────────

def txt_to_pdf(src: Path, dst: Path):
    content = src.read_text(encoding='utf-8')

    pdf = ChinesePDF('P')
    pdf.add_page()
    pdf.body_font(8.5)

    pw = pdf.w - 20  # 可用寬度 mm

    for raw in content.split('\n'):
        line = shorten_deco(raw)

        if not line.strip():
            pdf.ln(3)
            continue

        try:
            pdf.set_x(10)
            pdf.multi_cell(pw, 4.5, line, align='L')
        except Exception:
            try:
                pdf.set_x(10)
                pdf.multi_cell(pw, 4.5, line[:70], align='L')
            except Exception:
                pass

    pdf.output(str(dst))
    kb = os.path.getsize(dst) / 1024
    print(f"  OK  {dst.name}  ({kb:.0f} KB)")


# ── MD → PDF ─────────────────────────────────

def md_to_pdf(src: Path, dst: Path):
    content = src.read_text(encoding='utf-8')

    pdf = ChinesePDF('P')
    pdf.add_page()

    pw = pdf.w - 20

    for line in content.split('\n'):
        # 標題
        if line.startswith('# '):
            pdf.body_font(15)
            pdf.set_x(10)
            pdf.multi_cell(pw, 8, line[2:].strip(), align='L')
            pdf.ln(2)
            pdf.body_font(9)
            continue
        if line.startswith('## '):
            pdf.body_font(12)
            pdf.set_x(10)
            pdf.multi_cell(pw, 7, line[3:].strip(), align='L')
            pdf.ln(1)
            pdf.body_font(9)
            continue
        if line.startswith('### '):
            pdf.body_font(10.5)
            pdf.set_x(10)
            pdf.multi_cell(pw, 6, line[4:].strip(), align='L')
            pdf.body_font(9)
            continue

        # 水平線
        if re.match(r'^[-*_]{3,}\s*$', line.strip()):
            y = pdf.get_y()
            pdf.line(10, y, pdf.w - 10, y)
            pdf.ln(3)
            continue

        if not line.strip():
            pdf.ln(3)
            continue

        try:
            pdf.set_x(10)
            pdf.multi_cell(pw, 4.5, line, align='L')
        except Exception:
            try:
                pdf.set_x(10)
                pdf.multi_cell(pw, 4.5, line[:90], align='L')
            except Exception:
                pass

    pdf.output(str(dst))
    kb = os.path.getsize(dst) / 1024
    print(f"  OK  {dst.name}  ({kb:.0f} KB)")


# ── CSV → PDF (表格) ─────────────────────────

def csv_to_pdf(src: Path, dst: Path):
    with open(src, 'r', encoding='utf-8') as f:
        rows = list(csv.reader(f))

    if not rows:
        print(f"  SKIP  {src.name} (empty)")
        return

    header = rows[0]
    data = rows[1:]
    ncol = len(header)

    pdf = ChinesePDF('L')   # 橫向
    pdf.add_page()
    pdf.body_font(7)

    pw = pdf.w - 20
    # 依欄位字數估算寬度
    raw_w = [max(len(h) * 4 + 8, 18) for h in header]
    total = sum(raw_w)
    cw = [w / total * pw for w in raw_w]

    # 表頭
    pdf.set_fill_color(50, 80, 140)
    pdf.set_text_color(255, 255, 255)
    for i, h in enumerate(header):
        pdf.cell(cw[i], 6, h, border=1, fill=True, align='C')
    pdf.ln()

    # 資料列
    pdf.set_text_color(0, 0, 0)
    for ri, row in enumerate(data):
        bg = (240, 240, 248) if ri % 2 == 0 else (255, 255, 255)
        pdf.set_fill_color(*bg)
        for i in range(ncol):
            val = row[i] if i < len(row) else ''
            try:
                pdf.cell(cw[i], 5.5, val, border=1, fill=True, align='C')
            except Exception:
                pdf.cell(cw[i], 5.5, val[:12], border=1, fill=True, align='C')
        pdf.ln()

    pdf.output(str(dst))
    kb = os.path.getsize(dst) / 1024
    print(f"  OK  {dst.name}  ({kb:.0f} KB, {len(data)} rows)")


# ── 主程式 ───────────────────────────────────

def main():
    base = Path(__file__).parent.parent / "test-data" / "company-documents"

    print("=" * 55)
    print("  文件 → PDF 轉換工具 (fpdf2 + 微軟正黑體)")
    print("=" * 55)

    # TXT → PDF
    print("\n[TXT -> PDF]")
    for folder, name in [
        ("payroll",        "202601-E007-劉志明-薪資條.txt"),
        ("forms",          "請假單範本-E012-周秀蘭.txt"),
        ("contracts",      "勞動契約書-謝雅玲.txt"),
        ("health-records", "健康檢查報告-E016-高淑珍.txt"),
    ]:
        s = base / folder / name
        if s.exists():
            txt_to_pdf(s, s.with_suffix('.pdf'))
        else:
            print(f"  MISS  {s}")

    # MD → PDF
    print("\n[MD -> PDF]")
    for folder, name in [
        ("hr-regulations", "員工手冊-第一章-總則.md"),
        ("hr-regulations", "獎懲管理辦法.md"),
        ("sop",            "新人到職SOP.md"),
        ("sop",            "報帳作業規範.md"),
    ]:
        s = base / folder / name
        if s.exists():
            md_to_pdf(s, s.with_suffix('.pdf'))
        else:
            print(f"  MISS  {s}")

    # CSV → PDF
    print("\n[CSV -> PDF]")
    s = base / "employee-data" / "員工名冊.csv"
    if s.exists():
        csv_to_pdf(s, s.with_suffix('.pdf'))
    else:
        print(f"  MISS  {s}")

    # 統計
    pdfs = list(base.rglob("*.pdf"))
    total = sum(p.stat().st_size for p in pdfs)
    print(f"\n{'=' * 55}")
    print(f"  共 {len(pdfs)} 個 PDF ({total / 1024:.0f} KB)")
    print(f"{'=' * 55}")


if __name__ == "__main__":
    main()

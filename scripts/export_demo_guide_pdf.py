"""
Convert test-data/DEMO_GUIDE.md → test-data/DEMO_GUIDE.pdf
Uses: markdown + fpdf2 (already installed)
"""
import re
import sys
from pathlib import Path

import markdown
from fpdf import FPDF

# ── Paths ─────────────────────────────────────────────────────────────────────
BASE = Path(__file__).parent.parent / "test-data"
MD_PATH  = BASE / "DEMO_GUIDE.md"
PDF_PATH = BASE / "DEMO_GUIDE.pdf"

# ── Colours & fonts ───────────────────────────────────────────────────────────
C_NAVY   = (30, 64, 120)
C_BLUE   = (41, 98, 210)
C_LIGHT  = (239, 246, 255)
C_HEAD   = (248, 250, 252)
C_BORDER = (200, 213, 234)
C_TEXT   = (30, 30, 30)
C_MUTED  = (100, 110, 130)
C_GREEN  = (22, 140, 80)
C_RED    = (180, 20, 20)
C_ORANGE = (180, 100, 10)

class DemoPDF(FPDF):
    def __init__(self):
        super().__init__()
        # Register Microsoft JhengHei (Traditional Chinese + Latin)
        # Both regular and bold registered under same family "msjh"
        self.add_font("msjh", "",  r"C:\Windows\Fonts\msjh.ttc")
        self.add_font("msjh", "B", r"C:\Windows\Fonts\msjhbd.ttc")

    def set_default_font(self, bold=False, size=9):
        self.set_font("msjh", "B" if bold else "", size)

    def header(self):
        self.set_fill_color(*C_NAVY)
        self.rect(0, 0, 210, 12, 'F')
        self.set_default_font(bold=True, size=9)
        self.set_text_color(255, 255, 255)
        self.set_xy(10, 2)
        self.cell(0, 8, "Enclave AI 勞資法務助手 — Demo 指南  v1.1", align="L")
        self.set_xy(0, 2)
        self.cell(200, 8, "2026-02-23", align="R")

    def footer(self):
        self.set_y(-12)
        self.set_default_font(size=8)
        self.set_text_color(*C_MUTED)
        self.cell(0, 8, f"— {self.page_no()} —", align="C")

    def section_title(self, text, level=1):
        self.ln(4)
        if level == 1:
            self.set_fill_color(*C_NAVY)
            self.set_text_color(255, 255, 255)
            self.set_default_font(bold=True, size=13)
            self.cell(0, 9, "  " + text, fill=True, ln=True)
        elif level == 2:
            self.set_fill_color(*C_LIGHT)
            self.set_text_color(*C_NAVY)
            self.set_default_font(bold=True, size=11)
            self.cell(0, 8, "  " + text, fill=True, border="LB", ln=True)
        else:
            self.set_text_color(*C_BLUE)
            self.set_default_font(bold=True, size=10)
            self.cell(0, 7, text, ln=True)
            self.set_text_color(*C_TEXT)
        self.ln(1)

    def para(self, text, indent=0):
        self.set_default_font(size=9)
        self.set_text_color(*C_TEXT)
        self.set_x(10 + indent)
        clean = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
        clean = re.sub(r'`(.+?)`', r'\1', clean)
        clean = re.sub(r'_(.+?)_', r'\1', clean)
        self.multi_cell(190 - indent, 5, clean, ln=True)

    def bullet(self, text, level=1):
        self.set_default_font(size=9)
        self.set_text_color(*C_TEXT)
        indent = 10 + (level - 1) * 8
        self.set_x(indent)
        self.cell(5, 5, "-")
        clean = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
        clean = re.sub(r'`(.+?)`', r'\1', clean)
        clean = re.sub(r'_(.+?)_', r'\1', clean)
        self.multi_cell(175 - (level - 1) * 8, 5, clean, ln=True)

    def blockquote(self, text):
        self.set_fill_color(*C_LIGHT)
        self.set_x(14)
        clean = re.sub(r'\*(.+?)\*', r'\1', text.lstrip('> '))
        clean = re.sub(r'`(.+?)`', r'\1', clean)
        self.set_default_font(size=8)
        self.set_text_color(*C_BLUE)
        self.multi_cell(182, 5, clean, border="L", fill=True, ln=True)
        self.set_text_color(*C_TEXT)

    def draw_table(self, headers, rows, col_widths=None):
        self.ln(1)
        n = len(headers)
        page_w = 190
        if col_widths is None:
            col_widths = [page_w / n] * n

        # Header row
        self.set_fill_color(*C_NAVY)
        self.set_text_color(255, 255, 255)
        self.set_default_font(bold=True, size=8)
        self.set_x(10)
        for i, h in enumerate(headers):
            h_clean = h.replace('**', '').replace('*', '')
            self.cell(col_widths[i], 6, h_clean, border=1, fill=True, align="C")
        self.ln()

        self.set_default_font(size=8)
        for ri, row in enumerate(rows):
            fill = ri % 2 == 0
            self.set_fill_color(*(C_HEAD if fill else (255, 255, 255)))
            self.set_x(10)
            row_h = 0
            for ci, cell_val in enumerate(row):
                clean = re.sub(r'\*\*(.+?)\*\*', r'\1', str(cell_val))
                clean = re.sub(r'`(.+?)`', r'\1', clean)
                n_lines = max(1, len(clean) // max(1, int(col_widths[ci] / 2.5)))
                row_h = max(row_h, n_lines * 5 + 2)
            row_h = min(row_h, 20)

            if self.get_y() + row_h > 280:
                self.add_page()
                self.set_fill_color(*C_NAVY)
                self.set_text_color(255, 255, 255)
                self.set_default_font(bold=True, size=8)
                self.set_x(10)
                for i, h in enumerate(headers):
                    self.cell(col_widths[i], 6, h.replace('**', ''), border=1, fill=True, align="C")
                self.ln()
                self.set_default_font(size=8)

            self.set_text_color(*C_TEXT)
            self.set_x(10)
            cur_y = self.get_y()
            for ci, cell_val in enumerate(row):
                clean = re.sub(r'\*\*(.+?)\*\*', r'\1', str(cell_val))
                clean = re.sub(r'`(.+?)`', r'\1', clean)
                clean = clean.replace('[X]', '違法').replace('[OK]', '合規').replace('[!]', '注意').replace('🏆', '優')
                x_before = self.get_x()
                self.multi_cell(col_widths[ci], row_h, clean, border=1, fill=fill, align="L", ln=3)
                self.set_xy(x_before + col_widths[ci], cur_y)
            self.set_y(cur_y + row_h)
        self.ln(2)


# ── Parse markdown into blocks ────────────────────────────────────────────────
def parse_md(path):
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    blocks = []
    i = 0
    while i < len(lines):
        line = lines[i]
        # Headings
        if line.startswith('### '):
            blocks.append(('h3', line[4:]))
        elif line.startswith('## '):
            blocks.append(('h2', line[3:]))
        elif line.startswith('# '):
            blocks.append(('h1', line[2:]))
        # Horizontal rule
        elif line.strip() in ('---', '***', '___'):
            blocks.append(('hr', ''))
        # Blockquote
        elif line.startswith('> '):
            blocks.append(('bq', line[2:]))
        # Table
        elif '|' in line and i + 1 < len(lines) and '|' in lines[i + 1] and '---' in lines[i + 1]:
            headers = [c.strip() for c in line.strip('|').split('|')]
            i += 2  # skip separator
            rows = []
            while i < len(lines) and '|' in lines[i]:
                row = [c.strip() for c in lines[i].strip('|').split('|')]
                rows.append(row)
                i += 1
            blocks.append(('table', (headers, rows)))
            continue
        # Bullet list
        elif re.match(r'^(\s*)([-*+]|\d+\.)\s', line):
            m = re.match(r'^(\s*)([-*+]|\d+\.)\s(.*)', line)
            lvl = len(m.group(1)) // 2 + 1
            blocks.append(('li', (m.group(3), lvl)))
        # Empty line
        elif line.strip() == '':
            blocks.append(('blank', ''))
        # Normal paragraph
        else:
            blocks.append(('p', line))
        i += 1
    return blocks


# ── Render ────────────────────────────────────────────────────────────────────
def render(blocks):
    pdf = DemoPDF()
    pdf.set_auto_page_break(True, margin=15)
    pdf.add_page()

    blank_count = 0
    for kind, content in blocks:
        if kind == 'blank':
            blank_count += 1
            if blank_count <= 1:
                pdf.ln(2)
            continue
        blank_count = 0

        if kind == 'h1':
            pdf.section_title(content, 1)
        elif kind == 'h2':
            pdf.section_title(content, 2)
        elif kind == 'h3':
            pdf.section_title(content, 3)
        elif kind == 'hr':
            pdf.set_draw_color(*C_BORDER)
            pdf.line(10, pdf.get_y(), 200, pdf.get_y())
            pdf.ln(2)
        elif kind == 'bq':
            pdf.blockquote(content)
        elif kind == 'table':
            headers, rows = content
            n = len(headers)
            # Adjust column widths by content type
            if n == 2:
                cw = [60, 130]
            elif n == 3:
                cw = [40, 80, 70]
            elif n == 4:
                cw = [25, 65, 65, 35]
            elif n == 5:
                cw = [20, 45, 55, 35, 35]
            elif n == 6:
                cw = [15, 35, 55, 45, 25, 15]
            else:
                cw = [190 // n] * n
            pdf.draw_table(headers, rows, cw)
        elif kind == 'li':
            text, lvl = content
            pdf.bullet(text, lvl)
        elif kind == 'p':
            if content.strip():
                pdf.para(content)

    return pdf


# ── Main ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print(f"Reading {MD_PATH} ...")
    blocks = parse_md(MD_PATH)
    print(f"  {len(blocks)} blocks parsed")
    pdf = render(blocks)
    pdf.output(str(PDF_PATH))
    print(f"✅ PDF saved to {PDF_PATH}")
    print(f"   Size: {PDF_PATH.stat().st_size // 1024} KB")

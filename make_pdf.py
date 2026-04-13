"""
Convert SETUP.md to SETUP.pdf using fpdf2.
Run once: python make_pdf.py
"""
import re
from pathlib import Path
from fpdf import FPDF

MD = Path("SETUP.md").read_text(encoding="utf-8")

# ── colour palette ────────────────────────────────────────────────────────────
C_TEXT      = (34,  34,  34)
C_H1        = (15,  76, 129)
C_H2        = (30, 100, 160)
C_H3        = (50, 120, 180)
C_CODE_BG   = (244, 244, 244)
C_CODE_FG   = (60,  60,  60)
C_BORDER    = (204, 204, 204)
C_TH_BG     = (230, 237, 245)
C_TD_ALT    = (250, 250, 250)
C_NOTE_BG   = (255, 253, 230)
C_NOTE_SIDE = (180, 160,   0)
C_HR        = (200, 200, 200)

MARGIN_L = 18
MARGIN_R = 18
MARGIN_T = 16
PAGE_W   = 210  # A4


def sanitize(text):
    """Replace non-latin-1 characters with ASCII equivalents."""
    return (text
        .replace("\u2014", "--")
        .replace("\u2013", "-")
        .replace("\u2019", "'")
        .replace("\u2018", "'")
        .replace("\u201c", '"')
        .replace("\u201d", '"')
        .replace("\u2026", "...")
        .replace("\u2022", "-")
        .replace("\u25e6", "-")
        .encode("latin-1", errors="replace").decode("latin-1")
    )


class PDF(FPDF):
    def header(self):
        pass  # no running header

    def footer(self):
        self.set_y(-12)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(*C_TEXT)
        self.cell(0, 5, f"Biometric Event Server -- Setup Guide   |   Page {self.page_no()}", align="C")

    # ── helpers ───────────────────────────────────────────────────────────────
    def usable_w(self):
        return PAGE_W - MARGIN_L - MARGIN_R

    def rule(self, color=C_HR, thickness=0.3):
        self.set_draw_color(*color)
        self.set_line_width(thickness)
        x = MARGIN_L
        y = self.get_y()
        self.line(x, y, PAGE_W - MARGIN_R, y)
        self.ln(3)

    def add_h1(self, text):
        self.ln(2)
        self.set_font("Helvetica", "B", 18)
        self.set_text_color(*C_H1)
        self.set_x(MARGIN_L)
        self.multi_cell(self.usable_w(), 8, sanitize(text))
        self.rule(C_H1, 0.6)
        self.ln(1)

    def add_h2(self, text):
        self.ln(4)
        self.set_font("Helvetica", "B", 13)
        self.set_text_color(*C_H2)
        self.set_x(MARGIN_L)
        self.multi_cell(self.usable_w(), 7, sanitize(text))
        self.rule(C_BORDER, 0.3)

    def add_h3(self, text):
        self.ln(3)
        self.set_font("Helvetica", "B", 11)
        self.set_text_color(*C_H3)
        self.set_x(MARGIN_L)
        self.multi_cell(self.usable_w(), 6, sanitize(text))
        self.ln(1)

    def inline_code(self, text):
        """Return text with inline backtick spans replaced — we handle them inline."""
        return text  # handled in add_para

    def add_para(self, text, indent=0):
        """Render a paragraph, handling **bold**, `code`, and plain text inline."""
        text = sanitize(text)
        if not text.strip():
            return
        # Split on bold and inline-code markers
        token_re = re.compile(r'(`[^`]+`|\*\*[^*]+\*\*)')
        parts = token_re.split(text)
        self.set_x(MARGIN_L + indent)
        line_h = 5.5

        for part in parts:
            if part.startswith('`') and part.endswith('`'):
                inner = part[1:-1]
                self.set_font("Courier", "", 9.5)
                self.set_text_color(*C_CODE_FG)
                self.set_fill_color(*C_CODE_BG)
                self.write(line_h, inner)
                self.set_text_color(*C_TEXT)
                self.set_fill_color(255, 255, 255)
            elif part.startswith('**') and part.endswith('**'):
                inner = part[2:-2]
                self.set_font("Helvetica", "B", 10)
                self.set_text_color(*C_TEXT)
                self.write(line_h, inner)
            else:
                self.set_font("Helvetica", "", 10)
                self.set_text_color(*C_TEXT)
                self.write(line_h, part)

        self.ln(line_h + 1)

    def add_code_block(self, lines):
        pad   = 4
        lh    = 4.8
        w     = self.usable_w()
        total = lh * len(lines) + pad * 2

        if self.get_y() + total > self.h - 20:
            self.add_page()

        y0 = self.get_y()
        self.set_fill_color(*C_CODE_BG)
        self.set_draw_color(*C_BORDER)
        self.set_line_width(0.3)
        self.rect(MARGIN_L, y0, w, total, style="FD")

        self.set_y(y0 + pad)
        self.set_font("Courier", "", 8.5)
        self.set_text_color(*C_CODE_FG)
        for line in lines:
            self.set_x(MARGIN_L + pad)
            self.cell(w - pad * 2, lh, sanitize(line), ln=True)

        self.ln(3)
        self.set_text_color(*C_TEXT)

    def add_blockquote(self, text):
        pad  = 4
        lh   = 5.5
        w    = self.usable_w()
        inner = sanitize(text.lstrip("> ").strip())

        self.set_fill_color(*C_NOTE_BG)
        self.set_draw_color(*C_NOTE_SIDE)
        self.set_line_width(1.2)

        y0 = self.get_y()
        self.set_x(MARGIN_L)
        # draw side bar
        self.line(MARGIN_L, y0, MARGIN_L, y0 + lh + pad * 2)

        self.set_fill_color(*C_NOTE_BG)
        self.rect(MARGIN_L, y0, w, lh + pad * 2, style="F")

        self.set_y(y0 + pad)
        self.set_x(MARGIN_L + pad + 1)
        self.set_font("Helvetica", "I", 9.5)
        self.set_text_color(90, 80, 0)
        self.multi_cell(w - pad * 2, lh, inner)
        self.ln(3)
        self.set_text_color(*C_TEXT)

    def add_bullet(self, text, level=0):
        text = sanitize(text)
        indent = MARGIN_L + level * 5
        bullet = "-" if level == 0 else " -"
        self.set_x(indent)
        self.set_font("Helvetica", "", 10)
        self.set_text_color(*C_TEXT)
        bw = 4
        self.cell(bw, 5.5, bullet)
        # render remainder with inline formatting
        token_re = re.compile(r'(`[^`]+`|\*\*[^*]+\*\*)')
        parts = token_re.split(text)
        for part in parts:
            if part.startswith('`') and part.endswith('`'):
                self.set_font("Courier", "", 9.5)
                self.set_text_color(*C_CODE_FG)
                self.write(5.5, part[1:-1])
                self.set_text_color(*C_TEXT)
            elif part.startswith('**') and part.endswith('**'):
                self.set_font("Helvetica", "B", 10)
                self.write(5.5, part[2:-2])
            else:
                self.set_font("Helvetica", "", 10)
                self.write(5.5, part)
        self.ln(5.5)

    def add_table(self, rows):
        """rows[0] = header, rows[1:] = data. All cells are plain text."""
        if not rows:
            return
        w     = self.usable_w()
        ncols = len(rows[0])
        # measure column widths proportionally (equal for now)
        col_w = w / ncols
        lh    = 6

        def _cell(text, is_header, alt):
            if is_header:
                self.set_fill_color(*C_TH_BG)
                self.set_font("Helvetica", "B", 9)
            elif alt:
                self.set_fill_color(*C_TD_ALT)
                self.set_font("Helvetica", "", 9)
            else:
                self.set_fill_color(255, 255, 255)
                self.set_font("Helvetica", "", 9)
            self.set_draw_color(*C_BORDER)
            self.set_line_width(0.2)
            self.set_text_color(*C_TEXT)
            self.cell(col_w, lh, sanitize(str(text))[:60], border=1, fill=True)

        for i, row in enumerate(rows):
            if self.get_y() + lh > self.h - 20:
                self.add_page()
            self.set_x(MARGIN_L)
            for cell in row:
                _cell(cell, i == 0, i % 2 == 0)
            self.ln(lh)
        self.ln(3)

    def add_hr(self):
        self.ln(3)
        self.rule(C_HR, 0.4)
        self.ln(3)


# ── parser ────────────────────────────────────────────────────────────────────

def parse_and_render(pdf, md):
    lines = md.splitlines()
    i = 0
    while i < len(lines):
        raw = lines[i]

        # fenced code block
        if raw.strip().startswith("```"):
            i += 1
            code_lines = []
            while i < len(lines) and not lines[i].strip().startswith("```"):
                code_lines.append(lines[i])
                i += 1
            pdf.add_code_block(code_lines)
            i += 1
            continue

        # headings
        if raw.startswith("# "):
            pdf.add_h1(raw[2:].strip())
            i += 1; continue
        if raw.startswith("## "):
            pdf.add_h2(raw[3:].strip())
            i += 1; continue
        if raw.startswith("### "):
            pdf.add_h3(raw[4:].strip())
            i += 1; continue

        # horizontal rule
        if re.match(r'^-{3,}$', raw.strip()):
            pdf.add_hr()
            i += 1; continue

        # blockquote
        if raw.startswith("> "):
            pdf.add_blockquote(raw)
            i += 1; continue

        # table — detect by | in line
        if "|" in raw and raw.strip().startswith("|"):
            table_rows = []
            while i < len(lines) and "|" in lines[i] and lines[i].strip().startswith("|"):
                row = lines[i]
                # skip separator rows like |---|---|
                if re.match(r'^\|[\s\-:|]+\|', row):
                    i += 1; continue
                cells = [c.strip() for c in row.strip().strip("|").split("|")]
                table_rows.append(cells)
                i += 1
            pdf.add_table(table_rows)
            continue

        # bullet
        m = re.match(r'^(\s*)[-*]\s+(.*)', raw)
        if m:
            level = len(m.group(1)) // 2
            pdf.add_bullet(m.group(2).strip(), level)
            i += 1; continue

        # blank line
        if not raw.strip():
            pdf.ln(2)
            i += 1; continue

        # numbered list item — treat like bullet
        m2 = re.match(r'^\d+\.\s+(.*)', raw)
        if m2:
            pdf.add_bullet(m2.group(1).strip())
            i += 1; continue

        # plain paragraph
        pdf.add_para(raw)
        i += 1


# ── main ──────────────────────────────────────────────────────────────────────
pdf = PDF(orientation="P", unit="mm", format="A4")
pdf.set_auto_page_break(auto=True, margin=18)
pdf.set_margins(MARGIN_L, MARGIN_T, MARGIN_R)
pdf.add_page()

parse_and_render(pdf, MD)

out = Path("SETUP.pdf")
pdf.output(str(out))
print(f"Written: {out}  ({out.stat().st_size // 1024} KB)")

"""
report_generator.py
-------------------
Generates downloadable report files (DOCX, PDF, JSON, Markdown) from the
12-section consulting report produced by the Report Agent.
"""

import base64
import io
import json
import urllib.request
from datetime import datetime
from docx import Document
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
from fpdf import FPDF

# Professional navy palette
_NAVY       = "1E3A5F"          # header fill
_NAVY_RGB   = RGBColor(30, 58, 95)
_ROW_ALT    = (232, 240, 254)   # alternating row tint (light blue-grey)


# ── Mermaid → PNG via mermaid.ink ────────────────────────────────────────────

def _get_diagram_png(plan_data: dict) -> bytes | None:
    """Render architecture diagram to PNG — PIL (reliable) preferred, Playwright fallback."""
    excalidraw_data = plan_data.get("excalidraw_diagram")
    if excalidraw_data and excalidraw_data.get("nodes"):
        # Try PIL renderer first (no CDN / internet required)
        try:
            from backend.excalidraw_utils import diagram_to_png
            png = diagram_to_png(excalidraw_data)
            if png:
                return png
        except Exception as e:
            print(f"[Diagram] PIL render failed: {e}")
        # Playwright fallback
        try:
            from backend.excalidraw_utils import build_excalidraw_json, excalidraw_to_png
            scene = build_excalidraw_json(excalidraw_data)
            png = excalidraw_to_png(scene)
            if png:
                return png
        except Exception as e:
            print(f"[Diagram] Playwright render failed: {e}")

    # Last resort: mermaid.ink (requires internet)
    mermaid = plan_data.get("mermaid_diagram", "")
    if mermaid and mermaid.strip():
        try:
            encoded = base64.urlsafe_b64encode(mermaid.strip().encode()).decode()
            url = f"https://mermaid.ink/img/{encoded}"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                return resp.read()
        except Exception:
            pass
    return None


# ── DOCX helpers ─────────────────────────────────────────────────────────────

def _shade_cell(cell, hex_color: str):
    """Apply a background fill colour to a DOCX table cell."""
    tc = cell._tc
    tcPr = tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), hex_color)
    tcPr.append(shd)


def _add_table_docx(doc, headers: list, rows: list, col_widths: list = None):
    """Add a styled table (navy header) to a DOCX document."""
    n_cols = len(headers)
    if n_cols == 0:
        return
    table = doc.add_table(rows=1, cols=n_cols)
    try:
        table.style = "Table Grid"
    except Exception:
        pass

    # Header row
    hdr_cells = table.rows[0].cells
    for i, h in enumerate(headers):
        cell = hdr_cells[i]
        para = cell.paragraphs[0]
        para.clear()
        run = para.add_run(str(h))
        run.bold = True
        run.font.size = Pt(10)
        run.font.color.rgb = RGBColor(255, 255, 255)
        para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        _shade_cell(cell, _NAVY)

    # Data rows
    for row_data in rows:
        row = table.add_row()
        for i, cell_text in enumerate(row_data):
            if i < len(row.cells):
                row.cells[i].text = str(cell_text) if cell_text is not None else ""

    # Apply column widths after all rows exist
    if col_widths:
        for row in table.rows:
            for i, w in enumerate(col_widths):
                if i < len(row.cells):
                    row.cells[i].width = w

    doc.add_paragraph()


def _section_heading_docx(doc, text: str, level: int = 1):
    h = doc.add_heading(text, level=level)
    if h.runs:
        h.runs[0].font.color.rgb = RGBColor(30, 58, 95)


# ── PDF helpers ───────────────────────────────────────────────────────────────

class ReportPDF(FPDF):
    def header(self):
        self.set_font("Helvetica", "B", 12)
        self.set_text_color(30, 58, 95)
        self.cell(0, 10, "AI-Powered POC Generator - Project Report", new_x="LMARGIN", new_y="NEXT", align="C")
        self.ln(1)
        self.set_draw_color(30, 58, 95)
        self.line(10, self.get_y(), 200, self.get_y())
        self.ln(4)

    def footer(self):
        self.set_y(-15)
        self.set_font("Helvetica", "", 8)
        self.set_text_color(128, 128, 128)
        self.cell(0, 10, f"Page {self.page_no()}", align="C")

    def section_title(self, title: str):
        self.ln(4)
        self.set_font("Helvetica", "B", 12)
        self.set_text_color(30, 58, 95)
        self.cell(0, 8, _safe(title), new_x="LMARGIN", new_y="NEXT")
        self.set_draw_color(30, 58, 95)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.ln(3)

    def subsection_title(self, title: str):
        self.ln(2)
        self.set_font("Helvetica", "B", 10)
        self.set_text_color(60, 60, 60)
        self.cell(0, 7, _safe(title), new_x="LMARGIN", new_y="NEXT")
        self.ln(1)

    def paragraph(self, body: str):
        self.set_font("Helvetica", "", 10)
        self.set_text_color(50, 50, 50)
        safe = _safe(body)
        if len(safe) > 5000:
            safe = safe[:4997] + "..."
        self.multi_cell(0, 6, safe)
        self.ln(2)

    def simple_table(self, headers: list, rows: list, col_widths: list = None):
        """Draw a table with a navy header and alternating row shading."""
        if not headers:
            return
        usable = self.w - self.l_margin - self.r_margin
        if col_widths is None:
            col_widths = [usable / len(headers)] * len(headers)
        row_h = 7

        if self.get_y() > self.h - 40:
            self.add_page()

        # Header
        self.set_fill_color(30, 58, 95)
        self.set_text_color(255, 255, 255)
        self.set_font("Helvetica", "B", 9)
        for h, w in zip(headers, col_widths):
            self.cell(w, row_h, _safe(str(h))[:40], border=1, align="C", fill=True)
        self.ln()

        # Data rows
        self.set_font("Helvetica", "", 9)
        for idx, row_data in enumerate(rows):
            if self.get_y() > self.h - 20:
                self.add_page()
                self.set_fill_color(30, 58, 95)
                self.set_text_color(255, 255, 255)
                self.set_font("Helvetica", "B", 9)
                for h, w in zip(headers, col_widths):
                    self.cell(w, row_h, _safe(str(h))[:40], border=1, align="C", fill=True)
                self.ln()
                self.set_font("Helvetica", "", 9)

            fill = idx % 2 == 0
            if fill:
                self.set_fill_color(*_ROW_ALT)
            else:
                self.set_fill_color(255, 255, 255)
            self.set_text_color(40, 40, 40)
            for cell_text, w in zip(row_data, col_widths):
                safe = _safe(str(cell_text) if cell_text else "")
                if len(safe) > 90:
                    safe = safe[:87] + "..."
                self.cell(w, row_h, safe, border=1, fill=fill)
            self.ln()

        self.ln(3)


def _safe(text: str) -> str:
    """Encode text to latin-1 safe representation for fpdf core fonts."""
    return str(text).encode("latin-1", errors="replace").decode("latin-1")


# ── Markdown helpers ──────────────────────────────────────────────────────────

def _md_table(headers: list, rows: list) -> str:
    if not rows:
        return ""
    lines = [
        "| " + " | ".join(str(h) for h in headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(str(c).replace("|", "\\|") for c in row) + " |")
    return "\n".join(lines)


def _md_list_table(header: str, items: list) -> str:
    return _md_table([header], [[item] for item in items])


# ── Public generator functions ────────────────────────────────────────────────

def _set_body_font(paragraph, size_pt: float = 11, color: RGBColor = None):
    """Apply Calibri body font to every run in a paragraph."""
    for run in paragraph.runs:
        run.font.name = "Calibri"
        run.font.size = Pt(size_pt)
        if color:
            run.font.color.rgb = color


def _add_body_para(doc, text: str, italic: bool = False) -> None:
    """Add a body paragraph with Calibri 11pt."""
    p = doc.add_paragraph()
    run = p.add_run(text)
    run.font.name = "Calibri"
    run.font.size = Pt(11)
    run.font.color.rgb = RGBColor(50, 50, 50)
    run.italic = italic
    pf = p.paragraph_format
    pf.space_after = Pt(6)
    pf.space_before = Pt(0)


def _add_bullet_docx(doc, text: str) -> None:
    """Add a clean bullet-list item (Calibri 11pt)."""
    p = doc.add_paragraph(style="List Bullet")
    run = p.add_run(text)
    run.font.name = "Calibri"
    run.font.size = Pt(11)
    run.font.color.rgb = RGBColor(50, 50, 50)
    p.paragraph_format.space_after = Pt(3)


def _section_h1(doc, text: str) -> None:
    """Section heading — Calibri 14pt Bold navy, with a thin rule below."""
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(14)
    p.paragraph_format.space_after  = Pt(4)
    run = p.add_run(text)
    run.font.name  = "Calibri Light"
    run.font.size  = Pt(14)
    run.font.bold  = True
    run.font.color.rgb = _NAVY_RGB
    # Bottom border (thin navy rule)
    from docx.oxml.ns import qn as _qn
    from docx.oxml import OxmlElement as _OE
    pPr = p._p.get_or_add_pPr()
    pBdr = _OE("w:pBdr")
    bottom = _OE("w:bottom")
    bottom.set(_qn("w:val"), "single")
    bottom.set(_qn("w:sz"), "4")
    bottom.set(_qn("w:space"), "4")
    bottom.set(_qn("w:color"), _NAVY)
    pBdr.append(bottom)
    pPr.append(pBdr)


def _section_h2(doc, text: str) -> None:
    """Sub-section heading — Calibri 11pt Bold navy."""
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(10)
    p.paragraph_format.space_after  = Pt(3)
    run = p.add_run(text)
    run.font.name  = "Calibri"
    run.font.size  = Pt(11)
    run.font.bold  = True
    run.font.color.rgb = _NAVY_RGB


def _clean_table(doc, headers: list, rows: list, col_widths: list = None):
    """Add a clean table: navy header, alternating light rows, Calibri 10pt."""
    if not headers:
        return
    n_cols = len(headers)
    table = doc.add_table(rows=1, cols=n_cols)
    table.style = "Table Grid"

    # Header row
    hdr_cells = table.rows[0].cells
    for i, h in enumerate(headers):
        cell = hdr_cells[i]
        para = cell.paragraphs[0]
        para.clear()
        run = para.add_run(str(h))
        run.bold = True
        run.font.name = "Calibri"
        run.font.size = Pt(10)
        run.font.color.rgb = RGBColor(255, 255, 255)
        para.alignment = WD_ALIGN_PARAGRAPH.LEFT
        _shade_cell(cell, _NAVY)

    # Data rows
    for idx, row_data in enumerate(rows):
        row = table.add_row()
        fill = "F0F4FF" if idx % 2 == 0 else "FFFFFF"
        for i, cell_text in enumerate(row_data):
            if i < len(row.cells):
                cell = row.cells[i]
                cell.text = str(cell_text) if cell_text is not None else ""
                for p in cell.paragraphs:
                    for run in p.runs:
                        run.font.name = "Calibri"
                        run.font.size = Pt(10)
                _shade_cell(cell, fill)

    if col_widths:
        for row in table.rows:
            for i, w in enumerate(col_widths):
                if i < len(row.cells):
                    row.cells[i].width = w

    doc.add_paragraph().paragraph_format.space_after = Pt(6)


def generate_docx(report_data: dict) -> io.BytesIO:
    """Generate a clean Word (.docx) consulting report — readable prose + minimal tables."""
    doc  = Document()
    raw  = report_data.get("raw_data", {})
    plan_data = raw.get("plan", {})

    # ── Document-level defaults ───────────────────────────────────────────────
    style = doc.styles["Normal"]
    style.font.name = "Calibri"
    style.font.size = Pt(11)
    from docx.oxml.ns import qn as _qn2
    style.element.rPr.rFonts.set(_qn2("w:asciiTheme"), "minorHAnsi")

    # ── Title block ──────────────────────────────────────────────────────────
    title = doc.add_heading("Project Consulting Report", level=0)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    if title.runs:
        title.runs[0].font.name = "Calibri Light"
        title.runs[0].font.color.rgb = _NAVY_RGB
        title.runs[0].font.size = Pt(24)

    sub = doc.add_paragraph()
    sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
    sub_run = sub.add_run(f"Generated on {datetime.now().strftime('%B %d, %Y')}")
    sub_run.font.name = "Calibri"
    sub_run.font.size = Pt(10)
    sub_run.font.color.rgb = RGBColor(120, 120, 120)
    sub_run.italic = True
    doc.add_paragraph()

    # ── 1. Executive Summary ──────────────────────────────────────────────────
    _section_h1(doc, "1. Executive Summary")
    _add_body_para(doc, report_data.get("executive_summary", ""))

    # ── 2. Background Summary ─────────────────────────────────────────────────
    _section_h1(doc, "2. Background Summary")
    _add_body_para(doc, report_data.get("background_summary", ""))

    # ── 3. Problem / Need Analysis ────────────────────────────────────────────
    _section_h1(doc, "3. Problem / Need Analysis")
    pna = report_data.get("problem_need_analysis", [])
    if pna:
        rows = [(r.get("problem_need", ""), r.get("business_impact", "")) for r in pna]
        _clean_table(doc, ["Problem / Need", "Business Impact"], rows,
                     col_widths=[Inches(2.8), Inches(3.8)])

    # ── 4. Requirements Analysis ──────────────────────────────────────────────
    _section_h1(doc, "4. Requirements Analysis")

    fr = report_data.get("functional_requirements", [])
    if fr:
        _section_h2(doc, "Functional Requirements")
        rows = [(r.get("id", ""), r.get("requirement", "")) for r in fr]
        _clean_table(doc, ["ID", "Requirement"], rows, col_widths=[Inches(0.8), Inches(5.8)])

    nfr = report_data.get("non_functional_requirements", [])
    if nfr:
        _section_h2(doc, "Non-Functional Requirements")
        rows = [(r.get("category", ""), r.get("requirement", "")) for r in nfr]
        _clean_table(doc, ["Category", "Requirement"], rows, col_widths=[Inches(1.6), Inches(5.0)])

    constraints = report_data.get("constraints", [])
    if constraints:
        _section_h2(doc, "Constraints")
        for c in constraints:
            _add_bullet_docx(doc, c)

    goals = report_data.get("business_goals", [])
    if goals:
        _section_h2(doc, "Business Goals")
        for g in goals:
            _add_bullet_docx(doc, g)

    tech_ctx = report_data.get("technology_context", [])
    if tech_ctx:
        _section_h2(doc, "Technology Context")
        for t in tech_ctx:
            _add_bullet_docx(doc, t)

    # ── 5. Assumptions ────────────────────────────────────────────────────────
    _section_h1(doc, "5. Assumptions")
    for a in report_data.get("assumptions", []):
        _add_bullet_docx(doc, a)

    # ── 6. Feature & Module Breakdown ─────────────────────────────────────────
    _section_h1(doc, "6. Feature & Module Breakdown")
    fmb = report_data.get("feature_module_breakdown", [])
    if fmb:
        rows = [(r.get("module", ""), r.get("feature_functionality", ""), r.get("technologies_used", ""))
                for r in fmb]
        _clean_table(doc, ["Module", "Feature / Functionality", "Technologies Used"], rows,
                     col_widths=[Inches(1.4), Inches(3.0), Inches(2.2)])

    # ── 7. Solution Architecture ──────────────────────────────────────────────
    _section_h1(doc, "7. Solution Architecture")
    png_bytes = _get_diagram_png(plan_data)
    if png_bytes:
        doc.add_picture(io.BytesIO(png_bytes), width=Inches(6.2))
        doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
    else:
        _add_body_para(doc, "Architecture diagram could not be rendered.", italic=True)
    doc.add_paragraph().paragraph_format.space_after = Pt(4)

    # ── 8. Feasibility Assessment ─────────────────────────────────────────────
    _section_h1(doc, "8. Feasibility Assessment")
    ft = report_data.get("feasibility_table", [])
    if ft:
        rows = [(r.get("metric", ""), r.get("value", ""), r.get("reason", "")) for r in ft]
        _clean_table(doc, ["Metric", "Rating", "Justification"], rows,
                     col_widths=[Inches(1.6), Inches(1.2), Inches(3.8)])

    # ── 9. Risk Assessment ────────────────────────────────────────────────────
    _section_h1(doc, "9. Risk Assessment")
    ra = report_data.get("risk_assessment", [])
    if ra:
        rows = [(r.get("risk", ""), r.get("impact", ""), r.get("mitigation_strategy", "")) for r in ra]
        _clean_table(doc, ["Risk", "Impact", "Mitigation Strategy"], rows,
                     col_widths=[Inches(2.0), Inches(1.4), Inches(3.2)])

    # ── 10. Recommendations & Next Steps ──────────────────────────────────────
    _section_h1(doc, "10. Recommendations & Next Steps")
    _add_body_para(doc, report_data.get("recommendations_next_steps", ""))

    # ── 11. Architecture Summary ──────────────────────────────────────────────
    _section_h1(doc, "11. Architecture Summary")
    _add_body_para(doc, report_data.get("architecture_summary", ""))

    buffer = io.BytesIO()
    doc.save(buffer)
    buffer.seek(0)
    return buffer


def generate_pdf(report_data: dict) -> io.BytesIO:
    """Generate PDF via Markdown → fpdf2 (no external binary required)."""
    raw = report_data.get("raw_data", {})
    plan_data = raw.get("plan", {})
    diagram_png = _get_diagram_png(plan_data)

    pdf = ReportPDF()
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.add_page()

    # Title block
    pdf.set_font("Helvetica", "B", 20)
    pdf.set_text_color(30, 58, 95)
    pdf.cell(0, 12, "Project Consulting Report", new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(120, 120, 120)
    pdf.cell(0, 7, f"Generated on {datetime.now().strftime('%Y-%m-%d %H:%M')}", new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.ln(6)

    def bullet_list(items: list):
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(50, 50, 50)
        for item in items:
            pdf.cell(5, 6, "")
            pdf.multi_cell(0, 6, _safe(f"•  {item}"))

    # 1. Executive Summary
    pdf.section_title("1. Executive Summary")
    pdf.paragraph(report_data.get("executive_summary", ""))

    # 2. Background Summary
    pdf.section_title("2. Background Summary")
    pdf.paragraph(report_data.get("background_summary", ""))

    # 3. Problem / Need Analysis
    pdf.section_title("3. Problem / Need Analysis")
    rows = [
        (r.get("problem_need", ""), r.get("business_impact", ""))
        for r in report_data.get("problem_need_analysis", [])
    ]
    pdf.simple_table(["Problem / Need", "Business Impact"], rows, [95, 95])

    # 4. Requirements Analysis
    pdf.section_title("4. Requirements Analysis")
    pdf.subsection_title("Functional Requirements")
    rows = [(r.get("id", ""), r.get("requirement", "")) for r in report_data.get("functional_requirements", [])]
    pdf.simple_table(["ID", "Requirement"], rows, [25, 165])

    pdf.subsection_title("Non-Functional Requirements")
    rows = [(r.get("category", ""), r.get("requirement", "")) for r in report_data.get("non_functional_requirements", [])]
    pdf.simple_table(["Category", "Requirement"], rows, [45, 145])

    pdf.subsection_title("Constraints")
    bullet_list(report_data.get("constraints", []))
    pdf.ln(3)

    pdf.subsection_title("Business Goals")
    bullet_list(report_data.get("business_goals", []))
    pdf.ln(3)

    pdf.subsection_title("Technology Context")
    bullet_list(report_data.get("technology_context", []))
    pdf.ln(3)

    # 5. Assumptions
    pdf.section_title("5. Assumptions")
    bullet_list(report_data.get("assumptions", []))
    pdf.ln(3)

    # 6. Feature & Module Breakdown
    pdf.section_title("6. Feature & Module Breakdown")
    rows = [
        (r.get("module", ""), r.get("feature_functionality", ""), r.get("technologies_used", ""))
        for r in report_data.get("feature_module_breakdown", [])
    ]
    pdf.simple_table(["Module", "Feature / Functionality", "Technologies Used"], rows, [45, 100, 45])

    # 7. Solution Architecture
    pdf.section_title("7. Solution Architecture")
    if diagram_png:
        try:
            img_buf = io.BytesIO(diagram_png)
            pdf.image(img_buf, w=180)
            pdf.ln(4)
        except Exception:
            pdf.paragraph("Architecture diagram could not be rendered.")
    else:
        pdf.paragraph("Architecture diagram not available.")

    # 8. Feasibility Assessment
    pdf.section_title("8. Feasibility Assessment")
    rows = [
        (r.get("metric", ""), r.get("value", ""), r.get("reason", ""))
        for r in report_data.get("feasibility_table", [])
    ]
    pdf.simple_table(["Metric", "Value", "Reason"], rows, [50, 30, 110])

    # 9. Risk Assessment
    pdf.section_title("9. Risk Assessment")
    rows = [
        (r.get("risk", ""), r.get("impact", ""), r.get("mitigation_strategy", ""))
        for r in report_data.get("risk_assessment", [])
    ]
    pdf.simple_table(["Risk", "Impact", "Mitigation Strategy"], rows, [55, 40, 95])

    # 10. Recommendations & Next Steps
    pdf.section_title("10. Recommendations & Next Steps")
    pdf.paragraph(report_data.get("recommendations_next_steps", ""))

    # 11. Architecture Summary
    pdf.section_title("11. Architecture Summary")
    pdf.paragraph(report_data.get("architecture_summary", ""))

    buffer = io.BytesIO()
    buffer.write(pdf.output())
    buffer.seek(0)
    return buffer


def generate_json(report_data: dict) -> io.BytesIO:
    """Generate a JSON export of the full report."""
    buffer = io.BytesIO()
    buffer.write(json.dumps(report_data, indent=2).encode("utf-8"))
    buffer.seek(0)
    return buffer


def generate_markdown(report_data: dict) -> io.BytesIO:
    """Generate a Markdown report following the 11-section consulting format."""
    raw = report_data.get("raw_data", {})
    plan_data = raw.get("plan", {})
    mermaid = plan_data.get("mermaid_diagram", "")

    lines = [
        "# Project Consulting Report",
        "",
        f"_Generated on {datetime.now().strftime('%Y-%m-%d %H:%M')}_",
        "",
        "---",
        "",
    ]

    # 1
    lines += ["## 1. Executive Summary", "", report_data.get("executive_summary", ""), "", "---", ""]

    # 2
    lines += ["## 2. Background Summary", "", report_data.get("background_summary", ""), "", "---", ""]

    # 3
    lines.append("## 3. Problem / Need Analysis")
    lines.append("")
    rows = [
        (r.get("problem_need", ""), r.get("business_impact", ""))
        for r in report_data.get("problem_need_analysis", [])
    ]
    lines.append(_md_table(["Problem / Need", "Business Impact"], rows))
    lines += ["", "---", ""]

    # 4
    lines.append("## 4. Requirements Analysis")
    lines.append("")

    lines.append("### Functional Requirements")
    lines.append("")
    rows = [
        (r.get("id", ""), r.get("requirement", ""))
        for r in report_data.get("functional_requirements", [])
    ]
    lines.append(_md_table(["ID", "Requirement"], rows))
    lines.append("")

    lines.append("### Non-Functional Requirements")
    lines.append("")
    rows = [
        (r.get("category", ""), r.get("requirement", ""))
        for r in report_data.get("non_functional_requirements", [])
    ]
    lines.append(_md_table(["Category", "Requirement"], rows))
    lines.append("")

    lines.append("### Constraints")
    lines.append("")
    lines.append(_md_list_table("Constraint", report_data.get("constraints", [])))
    lines.append("")

    lines.append("### Business Goals")
    lines.append("")
    lines.append(_md_list_table("Goal", report_data.get("business_goals", [])))
    lines.append("")

    lines.append("### Technology Context")
    lines.append("")
    lines.append(_md_list_table("Technology Context", report_data.get("technology_context", [])))
    lines += ["", "---", ""]

    # 5
    lines.append("## 5. Assumptions")
    lines.append("")
    lines.append(_md_list_table("Assumption", report_data.get("assumptions", [])))
    lines += ["", "---", ""]

    # 6
    lines.append("## 6. Feature & Module Breakdown")
    lines.append("")
    rows = [
        (r.get("module", ""), r.get("feature_functionality", ""), r.get("technologies_used", ""))
        for r in report_data.get("feature_module_breakdown", [])
    ]
    lines.append(_md_table(["Module", "Feature / Functionality", "Technologies Used"], rows))
    lines += ["", "---", ""]

    # 7
    lines.append("## 7. Solution Architecture")
    lines.append("")
    if mermaid:
        lines.append("```mermaid")
        lines.append(mermaid)
        lines.append("```")
    else:
        lines.append("_Architecture diagram not available._")
    lines += ["", "---", ""]

    # 8
    lines.append("## 8. Feasibility Assessment")
    lines.append("")
    rows = [
        (r.get("metric", ""), r.get("value", ""), r.get("reason", ""))
        for r in report_data.get("feasibility_table", [])
    ]
    lines.append(_md_table(["Metric", "Value", "Reason"], rows))
    lines += ["", "---", ""]

    # 9
    lines.append("## 9. Risk Assessment")
    lines.append("")
    rows = [
        (r.get("risk", ""), r.get("impact", ""), r.get("mitigation_strategy", ""))
        for r in report_data.get("risk_assessment", [])
    ]
    lines.append(_md_table(["Risk", "Impact", "Mitigation Strategy"], rows))
    lines += ["", "---", ""]

    # 10
    lines.append("## 10. Recommendations & Next Steps")
    lines.append("")
    lines.append(report_data.get("recommendations_next_steps", ""))
    lines += ["", "---", ""]

    # 11
    lines.append("## 11. Architecture Summary")
    lines.append("")
    lines.append(report_data.get("architecture_summary", ""))
    lines.append("")

    buffer = io.BytesIO()
    buffer.write("\n".join(lines).encode("utf-8"))
    buffer.seek(0)
    return buffer

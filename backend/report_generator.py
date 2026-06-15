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
    """Render architecture diagram to PNG — Excalidraw preferred, mermaid.ink fallback."""
    # Try Excalidraw first
    excalidraw_data = plan_data.get("excalidraw_diagram")
    if excalidraw_data and excalidraw_data.get("nodes"):
        try:
            from backend.excalidraw_utils import build_excalidraw_json, excalidraw_to_png
            scene = build_excalidraw_json(excalidraw_data)
            png = excalidraw_to_png(scene)
            if png:
                return png
        except Exception as e:
            print(f"[Diagram] Excalidraw render failed: {e}")

    # Fallback: mermaid.ink
    mermaid = plan_data.get("mermaid_diagram", "")
    if mermaid and mermaid.strip():
        try:
            encoded = base64.urlsafe_b64encode(mermaid.strip().encode()).decode()
            url = f"https://mermaid.ink/img/{encoded}"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=20) as resp:
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

def generate_docx(report_data: dict) -> io.BytesIO:
    """Generate a Word (.docx) report following the 11-section consulting format."""
    doc = Document()
    raw = report_data.get("raw_data", {})
    plan_data = raw.get("plan", {})
    mermaid = plan_data.get("mermaid_diagram", "")

    # Title page
    title = doc.add_heading("Project Consulting Report", level=0)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    if title.runs:
        title.runs[0].font.color.rgb = _NAVY_RGB
        title.runs[0].font.size = Pt(22)

    sub = doc.add_paragraph()
    sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
    sub_run = sub.add_run(f"Generated on {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    sub_run.font.size = Pt(10)
    sub_run.font.color.rgb = RGBColor(128, 128, 128)
    doc.add_paragraph()

    # 1. Executive Summary
    _section_heading_docx(doc, "1. Executive Summary")
    doc.add_paragraph(report_data.get("executive_summary", ""))
    doc.add_paragraph()

    # 2. Background Summary
    _section_heading_docx(doc, "2. Background Summary")
    doc.add_paragraph(report_data.get("background_summary", ""))
    doc.add_paragraph()

    # 3. Problem / Need Analysis
    _section_heading_docx(doc, "3. Problem / Need Analysis")
    rows = [
        (r.get("problem_need", ""), r.get("business_impact", ""))
        for r in report_data.get("problem_need_analysis", [])
    ]
    _add_table_docx(doc, ["Problem / Need", "Business Impact"], rows,
                    col_widths=[Inches(2.8), Inches(3.8)])

    # 4. Requirements Analysis
    _section_heading_docx(doc, "4. Requirements Analysis")

    _section_heading_docx(doc, "Functional Requirements", level=2)
    rows = [
        (r.get("id", ""), r.get("requirement", ""))
        for r in report_data.get("functional_requirements", [])
    ]
    _add_table_docx(doc, ["ID", "Requirement"], rows, col_widths=[Inches(1.0), Inches(5.6)])

    _section_heading_docx(doc, "Non-Functional Requirements", level=2)
    rows = [
        (r.get("category", ""), r.get("requirement", ""))
        for r in report_data.get("non_functional_requirements", [])
    ]
    _add_table_docx(doc, ["Category", "Requirement"], rows, col_widths=[Inches(1.8), Inches(4.8)])

    _section_heading_docx(doc, "Constraints", level=2)
    _add_table_docx(doc, ["Constraint"], [[c] for c in report_data.get("constraints", [])])

    _section_heading_docx(doc, "Business Goals", level=2)
    _add_table_docx(doc, ["Goal"], [[g] for g in report_data.get("business_goals", [])])

    _section_heading_docx(doc, "Technology Context", level=2)
    _add_table_docx(doc, ["Technology Context"], [[t] for t in report_data.get("technology_context", [])])

    # 5. Assumptions
    _section_heading_docx(doc, "5. Assumptions")
    _add_table_docx(doc, ["Assumption"], [[a] for a in report_data.get("assumptions", [])])

    # 6. Feature & Module Breakdown
    _section_heading_docx(doc, "6. Feature & Module Breakdown")
    rows = [
        (r.get("module", ""), r.get("feature_functionality", ""), r.get("technologies_used", ""))
        for r in report_data.get("feature_module_breakdown", [])
    ]
    _add_table_docx(doc, ["Module", "Feature / Functionality", "Technologies Used"], rows,
                    col_widths=[Inches(1.5), Inches(2.8), Inches(2.3)])

    # 7. Solution Architecture
    _section_heading_docx(doc, "7. Solution Architecture")
    png_bytes = _get_diagram_png(plan_data)
    if png_bytes:
            doc.add_paragraph("Architecture Diagram:")
            doc.add_picture(io.BytesIO(png_bytes), width=Inches(6.0))
    else:
        doc.add_paragraph("Architecture diagram could not be rendered.")
    doc.add_paragraph()

    # 8. Feasibility Assessment
    _section_heading_docx(doc, "8. Feasibility Assessment")
    rows = [
        (r.get("metric", ""), r.get("value", ""), r.get("reason", ""))
        for r in report_data.get("feasibility_table", [])
    ]
    _add_table_docx(doc, ["Metric", "Value", "Reason"], rows,
                    col_widths=[Inches(1.8), Inches(1.2), Inches(3.6)])

    # 9. Risk Assessment
    _section_heading_docx(doc, "9. Risk Assessment")
    rows = [
        (r.get("risk", ""), r.get("impact", ""), r.get("mitigation_strategy", ""))
        for r in report_data.get("risk_assessment", [])
    ]
    _add_table_docx(doc, ["Risk", "Impact", "Mitigation Strategy"], rows,
                    col_widths=[Inches(2.2), Inches(1.5), Inches(2.9)])

    # 10. Recommendations & Next Steps
    _section_heading_docx(doc, "10. Recommendations & Next Steps")
    doc.add_paragraph(report_data.get("recommendations_next_steps", ""))
    doc.add_paragraph()

    # 11. Architecture Summary
    _section_heading_docx(doc, "11. Architecture Summary")
    doc.add_paragraph(report_data.get("architecture_summary", ""))
    doc.add_paragraph()

    buffer = io.BytesIO()
    doc.save(buffer)
    buffer.seek(0)
    return buffer


def generate_pdf(report_data: dict) -> io.BytesIO:
    """Generate PDF by converting Markdown → HTML → PDF (proper layout, no overlap)."""
    import base64
    import markdown as md_lib
    from weasyprint import HTML, CSS

    raw = report_data.get("raw_data", {})
    plan_data = raw.get("plan", {})

    # Render architecture diagram to PNG first (Excalidraw preferred)
    diagram_png = _get_diagram_png(plan_data)

    # Get the markdown content
    md_buf = generate_markdown(report_data)
    md_text = md_buf.read().decode("utf-8")

    # Convert markdown to HTML
    html_body = md_lib.markdown(md_text, extensions=["tables", "fenced_code", "nl2br"])

    # Inject diagram PNG (base64) into Section 7, replacing the placeholder
    if diagram_png:
        b64 = base64.b64encode(diagram_png).decode()
        img_tag = (
            f'<img src="data:image/png;base64,{b64}" '
            f'style="max-width:100%;height:auto;margin:12px 0;border:1px solid #CBD5E0;border-radius:4px;" />'
        )
        html_body = html_body.replace(
            "<em>Architecture diagram not available.</em>",
            img_tag,
        )

    # Build full HTML with professional CSS
    html_full = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  @page {{
    margin: 2cm 2.5cm;
    @bottom-right {{ content: "Page " counter(page); font-size: 9pt; color: #666; }}
  }}
  body {{
    font-family: "Helvetica Neue", Arial, sans-serif;
    font-size: 10pt;
    color: #1a1a2e;
    line-height: 1.6;
  }}
  h1 {{
    color: #1E3A5F;
    font-size: 22pt;
    text-align: center;
    border-bottom: 3px solid #1E3A5F;
    padding-bottom: 8px;
    margin-bottom: 4px;
  }}
  h2 {{
    color: #1E3A5F;
    font-size: 14pt;
    border-bottom: 1.5px solid #1E3A5F;
    padding-bottom: 4px;
    margin-top: 24px;
    page-break-after: avoid;
  }}
  h3 {{
    color: #2C5282;
    font-size: 11pt;
    margin-top: 16px;
    page-break-after: avoid;
  }}
  p {{ margin: 6px 0 10px 0; }}
  table {{
    width: 100%;
    border-collapse: collapse;
    margin: 12px 0;
    font-size: 9pt;
    page-break-inside: avoid;
  }}
  th {{
    background-color: #1E3A5F;
    color: #ffffff;
    padding: 7px 10px;
    text-align: left;
    font-weight: bold;
  }}
  td {{
    padding: 6px 10px;
    border: 1px solid #CBD5E0;
    vertical-align: top;
    word-wrap: break-word;
  }}
  tr:nth-child(even) td {{ background-color: #E8F0FE; }}
  tr:nth-child(odd) td  {{ background-color: #ffffff; }}
  code, pre {{
    font-family: "Courier New", monospace;
    font-size: 8pt;
    background: #F7FAFC;
    border: 1px solid #E2E8F0;
    border-radius: 3px;
    padding: 2px 4px;
    white-space: pre-wrap;
    word-break: break-all;
  }}
  pre {{ padding: 10px; margin: 8px 0; }}
  hr {{ border: none; border-top: 1px solid #CBD5E0; margin: 16px 0; }}
  ul, ol {{ margin: 6px 0 10px 1.2em; padding: 0; }}
  li {{ margin: 3px 0; }}
  em {{ color: #718096; font-size: 9pt; }}
</style>
</head>
<body>
{html_body}
</body>
</html>"""

    pdf_bytes = HTML(string=html_full).write_pdf()
    return io.BytesIO(pdf_bytes)


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

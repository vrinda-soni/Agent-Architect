"""
report_generator.py
-------------------
Generates downloadable report files (DOCX, PDF, JSON, Markdown)
from the Report Agent output.
"""

import io
import json
from datetime import datetime
from docx import Document
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from fpdf import FPDF


class ReportPDF(FPDF):
    def header(self):
        self.set_font("Helvetica", "B", 14)
        self.set_text_color(102, 34, 255)
        self.cell(0, 10, "AI-Powered POC Generator - Project Report", new_x="LMARGIN", new_y="NEXT", align="C")
        self.ln(2)
        self.set_draw_color(102, 34, 255)
        self.line(10, self.get_y(), 200, self.get_y())
        self.ln(5)

    def footer(self):
        self.set_y(-15)
        self.set_font("Helvetica", "", 8)
        self.set_text_color(128, 128, 128)
        self.cell(0, 10, f"Page {self.page_no()}", align="C")

    def chapter_title(self, title: str):
        self.set_font("Helvetica", "B", 13)
        self.set_text_color(0, 0, 0)
        self.cell(0, 10, title, new_x="LMARGIN", new_y="NEXT")
        self.ln(2)

    def chapter_body(self, body: str):
        self.set_font("Helvetica", "", 10)
        self.set_text_color(50, 50, 50)
        # Encode to latin-1 safe string to avoid Unicode issues with core fonts
        safe_body = body.encode("latin-1", errors="replace").decode("latin-1")
        # Truncate very long bodies to prevent rendering issues
        if len(safe_body) > 5000:
            safe_body = safe_body[:4997] + "..."
        self.multi_cell(0, 6, safe_body)
        self.ln()

    def bullet_list(self, items: list):
        self.set_font("Helvetica", "", 10)
        self.set_text_color(50, 50, 50)
        page_width = self.w - self.l_margin - self.r_margin
        for item in items:
            safe_item = item.encode("latin-1", errors="replace").decode("latin-1")
            # Truncate very long unbreakable strings to prevent horizontal space errors
            if len(safe_item) > 200:
                safe_item = safe_item[:197] + "..."
            x_start = self.get_x()
            self.cell(5, 6, "-", new_x="RIGHT", new_y="TOP")
            # Use explicit width to ensure proper wrapping
            self.multi_cell(page_width - 5, 6, f" {safe_item}")
        self.ln()


def generate_docx(report_data: dict) -> io.BytesIO:
    """Generate a DOCX report file."""
    doc = Document()

    # Title
    title = doc.add_heading("Project Report", level=0)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = title.runs[0]
    run.font.size = Pt(24)
    run.font.color.rgb = RGBColor(102, 34, 255)

    subtitle = doc.add_paragraph()
    subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER
    sub_run = subtitle.add_run(f"Generated on {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    sub_run.font.size = Pt(10)
    sub_run.font.color.rgb = RGBColor(128, 128, 128)

    doc.add_paragraph()

    def add_section(heading: str, content: str):
        if content:
            h = doc.add_heading(heading, level=1)
            h.runs[0].font.color.rgb = RGBColor(0, 0, 0)
            doc.add_paragraph(content)
            doc.add_paragraph()

    add_section("Executive Summary", report_data.get("executive_summary", ""))
    add_section("Requirements Summary", report_data.get("requirements_summary", ""))
    add_section("Architecture Overview", report_data.get("architecture_overview", ""))
    add_section("Feasibility Assessment", report_data.get("feasibility_assessment", ""))
    add_section("Effort Estimation Summary", report_data.get("effort_estimation_summary", ""))

    recommendations = report_data.get("recommendations", [])
    if recommendations:
        doc.add_heading("Recommendations", level=1)
        for rec in recommendations:
            p = doc.add_paragraph(style="List Bullet")
            p.add_run(rec)
        doc.add_paragraph()

    # Extra sections
    for section in report_data.get("sections", []):
        add_section(section.get("title", ""), section.get("content", ""))

    buffer = io.BytesIO()
    doc.save(buffer)
    buffer.seek(0)
    return buffer


def generate_pdf(report_data: dict) -> io.BytesIO:
    """Generate a PDF report file."""
    pdf = ReportPDF()
    pdf.add_page()

    pdf.set_font("Helvetica", "B", 16)
    pdf.set_text_color(102, 34, 255)
    pdf.cell(0, 10, "Project Report", new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(128, 128, 128)
    pdf.cell(0, 6, f"Generated on {datetime.now().strftime('%Y-%m-%d %H:%M')}", new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.ln(5)

    def add_section(title: str, body: str):
        if body:
            pdf.chapter_title(title)
            pdf.chapter_body(body)

    add_section("Executive Summary", report_data.get("executive_summary", ""))
    add_section("Requirements Summary", report_data.get("requirements_summary", ""))
    add_section("Architecture Overview", report_data.get("architecture_overview", ""))
    add_section("Feasibility Assessment", report_data.get("feasibility_assessment", ""))
    add_section("Effort Estimation Summary", report_data.get("effort_estimation_summary", ""))

    recommendations = report_data.get("recommendations", [])
    if recommendations:
        pdf.chapter_title("Recommendations")
        pdf.bullet_list(recommendations)

    for section in report_data.get("sections", []):
        add_section(section.get("title", ""), section.get("content", ""))

    buffer = io.BytesIO(pdf.output())
    return buffer


def generate_json(report_data: dict) -> io.BytesIO:
    """Generate a JSON report file."""
    buffer = io.BytesIO()
    buffer.write(json.dumps(report_data, indent=2).encode("utf-8"))
    buffer.seek(0)
    return buffer


def generate_markdown(report_data: dict) -> io.BytesIO:
    """Generate a Markdown report file."""
    lines = [
        "# Project Report",
        "",
        f"_Generated on {datetime.now().strftime('%Y-%m-%d %H:%M')}_",
        "",
    ]

    def add_section(title: str, body: str):
        if body:
            lines.extend([f"## {title}", "", body, ""])

    add_section("Executive Summary", report_data.get("executive_summary", ""))
    add_section("Requirements Summary", report_data.get("requirements_summary", ""))
    add_section("Architecture Overview", report_data.get("architecture_overview", ""))
    add_section("Feasibility Assessment", report_data.get("feasibility_assessment", ""))
    add_section("Effort Estimation Summary", report_data.get("effort_estimation_summary", ""))

    recommendations = report_data.get("recommendations", [])
    if recommendations:
        lines.extend(["## Recommendations", ""])
        for rec in recommendations:
            lines.append(f"- {rec}")
        lines.append("")

    for section in report_data.get("sections", []):
        add_section(section.get("title", ""), section.get("content", ""))

    buffer = io.BytesIO()
    buffer.write("\n".join(lines).encode("utf-8"))
    buffer.seek(0)
    return buffer

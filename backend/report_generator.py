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
        self.set_font("DejaVu", "B", 14)
        self.set_text_color(102, 34, 255)
        self.cell(0, 10, "AI-Powered POC Generator — Project Report", ln=True, align="C")
        self.ln(2)
        self.set_draw_color(102, 34, 255)
        self.line(10, self.get_y(), 200, self.get_y())
        self.ln(5)

    def footer(self):
        self.set_y(-15)
        self.set_font("DejaVu", "", 8)
        self.set_text_color(128, 128, 128)
        self.cell(0, 10, f"Page {self.page_no()}", align="C")

    def chapter_title(self, title: str):
        self.set_font("DejaVu", "B", 13)
        self.set_text_color(0, 0, 0)
        self.cell(0, 10, title, ln=True)
        self.ln(2)

    def chapter_body(self, body: str):
        self.set_font("DejaVu", "", 10)
        self.set_text_color(50, 50, 50)
        self.multi_cell(0, 6, body)
        self.ln()

    def bullet_list(self, items: list):
        self.set_font("DejaVu", "", 10)
        self.set_text_color(50, 50, 50)
        for item in items:
            self.cell(5, 6, "•", ln=0)
            self.multi_cell(0, 6, f" {item}")
        self.ln()


def _add_dejavu_fonts(pdf: FPDF):
    """Register DejaVu fonts for Unicode support in PDF."""
    # fpdf2 ships with DejaVu fonts built-in
    pdf.add_font("DejaVu", "", "DejaVuSans.ttf", uni=True)
    pdf.add_font("DejaVu", "B", "DejaVuSans-Bold.ttf", uni=True)
    pdf.add_font("DejaVu", "I", "DejaVuSans-Oblique.ttf", uni=True)


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
    _add_dejavu_fonts(pdf)
    pdf.add_page()

    pdf.set_font("DejaVu", "B", 16)
    pdf.set_text_color(102, 34, 255)
    pdf.cell(0, 10, "Project Report", ln=True, align="C")
    pdf.set_font("DejaVu", "", 9)
    pdf.set_text_color(128, 128, 128)
    pdf.cell(0, 6, f"Generated on {datetime.now().strftime('%Y-%m-%d %H:%M')}", ln=True, align="C")
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

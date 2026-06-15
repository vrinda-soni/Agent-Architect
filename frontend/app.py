# import sys
# from pathlib import Path

# # Streamlit's exec()-based runner can lose sys.path mutations; insert at front to be safe
# root_dir = Path(__file__).resolve().parent.parent
# if str(root_dir) not in sys.path:
#     sys.path.insert(0, str(root_dir))

# import html
# import io
# import json
# import streamlit as st
# import streamlit.components.v1 as components
# import pandas as pd
# import backend.supabase as db
# from backend.api.client import (
#     call_task_agent,
#     call_planning_agent,
#     call_feasibility_agent,
#     call_estimation_agent,
#     call_report_agent,
# )
# from backend.report_generator import generate_docx, generate_pdf, generate_json, generate_markdown
# from backend.rag.ingestion import ingest_document, delete_project_documents, list_project_documents, extract_text


# # ── Cached DB helpers (avoid repeated Supabase round-trips per render) ────────

# @st.cache_data(ttl=30, show_spinner=False)
# def _cached_get_projects(user_id: str):
#     return db.get_projects(user_id)

# @st.cache_data(ttl=15, show_spinner=False)
# def _cached_get_transcript(project_id: str):
#     return db.get_transcript(project_id)

# @st.cache_data(ttl=30, show_spinner=False)
# def _cached_list_documents(project_id: str):
#     return list_project_documents(project_id)


# COMPLEXITY_BADGES = {
#     "low": ("🟢", "Low"),
#     "medium": ("🟡", "Medium"),
#     "high": ("🟠", "High"),
#     "very high": ("🔴", "Very High"),
# }

# CONFIDENCE_BADGES = {
#     "high": ("🟢", "High"),
#     "medium": ("🟡", "Medium"),
#     "low": ("🔴", "Low"),
# }


# def level_badge_html(level: str, badge_map: dict) -> str:
#     key = (level or "").strip().lower()
#     emoji, label = badge_map.get(key, ("⚪", level or "Unknown"))
#     return f'<div class="level-badge">{emoji} {label}</div>'


# def _step_header(num: str, title: str, desc: str = "", color: str = "indigo") -> str:
#     """Render a styled step-number section header inside a card."""
#     palettes = {
#         "indigo": ("rgba(99,102,241,0.18)", "rgba(99,102,241,0.45)", "#818CF8"),
#         "green":  ("rgba(5,150,105,0.15)",   "rgba(5,150,105,0.45)",  "#34D399"),
#         "amber":  ("rgba(217,119,6,0.15)",    "rgba(217,119,6,0.45)",  "#FCD34D"),
#         "rose":   ("rgba(244,63,94,0.15)",    "rgba(244,63,94,0.45)",  "#FB7185"),
#         "violet": ("rgba(124,58,237,0.18)",   "rgba(124,58,237,0.45)", "#C4B5FD"),
#     }
#     bg, border, fg = palettes.get(color, palettes["indigo"])
#     desc_html = (
#         f'<div style="font-size:0.8rem;color:#475569;margin-top:3px;line-height:1.4">{desc}</div>'
#         if desc else ""
#     )
#     return (
#         f'<div style="display:flex;align-items:flex-start;gap:0.9rem;margin-bottom:1.1rem">'
#         f'<div style="min-width:30px;height:30px;border-radius:7px;background:{bg};'
#         f'border:1px solid {border};color:{fg};display:flex;align-items:center;'
#         f'justify-content:center;font-size:0.82rem;font-weight:700;flex-shrink:0">{num}</div>'
#         f'<div><div style="font-size:1rem;font-weight:600;color:#E2E8F0;line-height:1.3">'
#         f'{title}</div>{desc_html}</div></div>'
#     )


# def _pipeline_html(steps: list) -> str:
#     """Render a compact pipeline status list for the sidebar."""
#     html_parts = []
#     for label, done in steps:
#         dot = (
#             "background:#34D399;box-shadow:0 0 5px rgba(52,211,153,0.35)"
#             if done else "background:#1E293B;border:1px solid #334155"
#         )
#         txt_color = "#94A3B8" if done else "#3B4A5A"
#         icon = "✓" if done else "·"
#         icon_color = "#34D399" if done else "#3B4A5A"
#         html_parts.append(
#             f'<div style="display:flex;align-items:center;gap:8px;padding:4px 0;'
#             f'font-size:12.5px;color:{txt_color};font-family:Inter,sans-serif">'
#             f'<div style="width:7px;height:7px;border-radius:50%;flex-shrink:0;{dot}"></div>'
#             f'<span>{label}</span>'
#             f'<span style="margin-left:auto;font-size:11px;color:{icon_color};font-weight:700">{icon}</span>'
#             f'</div>'
#         )
#     return "\n".join(html_parts)


# def _sanitize_mermaid(diagram: str) -> str:
#     """Robustly clean LLM-generated mermaid diagrams for mermaid.js v10."""
#     import re
#     cleaned = diagram.strip()
#     # Strip markdown code fence
#     if cleaned.startswith("```"):
#         cleaned = cleaned.strip("`").strip()
#         if cleaned.startswith("mermaid"):
#             cleaned = cleaned[7:].strip()
#     # Replace semicolons with newlines (LLM often uses semicolons as separators)
#     cleaned = cleaned.replace(";", "\n")
#     # Normalise escaped newlines
#     cleaned = cleaned.replace("\\n", "\n")
#     # Remove non-printable / non-ASCII chars but keep brackets — they are required for Node[Label] syntax
#     cleaned = re.sub(r'[^\x20-\x7E\n\t]', '', cleaned)
#     # Fix arrow styles
#     cleaned = re.sub(r'-{3,}>', '-->', cleaned)
#     cleaned = re.sub(r'--+>', '-->', cleaned)
#     # Collapse blank lines
#     cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
#     # Rename mermaid reserved keywords when used as bare node IDs to avoid parse errors
#     _reserved = {"end": "EndNode", "start": "StartNode", "default": "DefaultNode"}
#     lines = []
#     for line in cleaned.split("\n"):
#         stripped = line.strip().lower()
#         # Skip declaration lines (flowchart TD, graph LR, etc.)
#         if any(stripped.startswith(v) for v in ("flowchart", "graph ", "subgraph", "end", "style", "classDef", "class ")):
#             lines.append(line.rstrip())
#             continue
#         for kw, repl in _reserved.items():
#             # Only rename bare node IDs (word boundary, followed by [ --> or whitespace or EOL)
#             line = re.sub(r'\b' + re.escape(kw) + r'\b(?=\s*[\[>\-\s]|$)', repl, line, flags=re.IGNORECASE)
#         lines.append(line.rstrip())
#     cleaned = "\n".join(lines)
#     # Ensure diagram starts with a valid declaration
#     first_line = cleaned.split("\n")[0].strip().lower()
#     valid_starts = ("flowchart", "graph ", "sequencediagram", "classdiagram",
#                     "statediagram", "erdiagram", "gantt", "pie", "mindmap")
#     if not any(first_line.startswith(v) for v in valid_starts):
#         cleaned = "flowchart TD\n" + cleaned
#     return cleaned.strip()


# def render_mermaid_diagram(diagram: str, height: int = 540) -> None:
#     cleaned = _sanitize_mermaid(diagram)
#     safe_diagram = html.escape(cleaned)
#     components.html(
#         f"""<!DOCTYPE html>
# <html>
# <head>
#     <script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
#     <style>
#         body {{
#             margin: 0;
#             padding: 16px;
#             background: #0B0D14;
#             font-family: 'Inter', 'Segoe UI', sans-serif;
#         }}
#         .mermaid {{
#             display: flex;
#             justify-content: center;
#         }}
#         .mermaid svg {{
#             max-width: 100%;
#             height: auto;
#         }}
#     </style>
# </head>
# <body>
#     <pre class="mermaid">{safe_diagram}</pre>
#     <script>
#         mermaid.initialize({{
#             startOnLoad: true,
#             theme: "dark",
#             flowchart: {{ curve: "basis", padding: 20, useMaxWidth: true }},
#             themeVariables: {{
#                 primaryColor: "#312E81",
#                 primaryTextColor: "#E2E8F0",
#                 primaryBorderColor: "#6366F1",
#                 lineColor: "#475569",
#                 secondaryColor: "#1E1B4B",
#                 tertiaryColor: "#0F172A",
#                 background: "#0B0D14",
#                 mainBkg: "#1E1B4B",
#                 nodeBorder: "#6366F1",
#                 clusterBkg: "#0F172A",
#                 titleColor: "#E2E8F0",
#                 edgeLabelBackground: "#1E293B",
#                 fontFamily: "'Inter', 'Segoe UI', sans-serif",
#                 fontSize: "14px"
#             }}
#         }});
#     </script>
# </body>
# </html>""",
#         height=height,
#         scrolling=True,
#     )
 
# # -------------------------------------------------------------
# # Premium Aesthetics & CSS Styling
# # -------------------------------------------------------------
# st.set_page_config(
#     page_title="AI-Powered POC Generator",
#     page_icon="⚡",
#     layout="wide",
#     initial_sidebar_state="expanded"
# )
 
# st.markdown("""
# <style>
#     @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap');

#     * { font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif !important; }

#     /* ── App background ──────────────────────────────────────────── */
#     .stApp { background: #0B0D14 !important; }

#     /* ── Typography ──────────────────────────────────────────────── */
#     .main-title {
#         font-size: 1.85rem;
#         font-weight: 700;
#         color: #E2E8F0;
#         letter-spacing: -0.3px;
#         margin-bottom: 0.2rem;
#         line-height: 1.25;
#     }

#     .subtitle {
#         color: #475569;
#         font-size: 0.92rem;
#         font-weight: 400;
#         margin-bottom: 1.5rem;
#     }

#     /* ── Cards ───────────────────────────────────────────────────── */
#     .glass-card {
#         background: rgba(255, 255, 255, 0.025);
#         border: 1px solid rgba(255, 255, 255, 0.07);
#         border-radius: 12px;
#         padding: 1.6rem 1.75rem;
#         margin-bottom: 1.1rem;
#     }

#     /* ── Accent bars ─────────────────────────────────────────────── */
#     .accent-bar {
#         height: 3px;
#         background: linear-gradient(90deg, #6366F1, #818CF8);
#         border-radius: 2px;
#         margin-bottom: 1.2rem;
#     }

#     .accent-bar-purple {
#         height: 3px;
#         background: linear-gradient(90deg, #7C3AED, #6366F1);
#         border-radius: 2px;
#         margin-bottom: 1.2rem;
#     }

#     .accent-bar-green {
#         height: 3px;
#         background: linear-gradient(90deg, #059669, #10B981);
#         border-radius: 2px;
#         margin-bottom: 1.2rem;
#     }

#     /* ── Status badges ───────────────────────────────────────────── */
#     .status-badge {
#         display: inline-flex;
#         align-items: center;
#         gap: 0.3rem;
#         padding: 0.28rem 0.65rem;
#         border-radius: 6px;
#         font-size: 0.7rem;
#         font-weight: 700;
#         text-transform: uppercase;
#         letter-spacing: 0.08em;
#         white-space: nowrap;
#         line-height: 1;
#     }

#     .status-completed {
#         background: rgba(5, 150, 105, 0.12);
#         color: #34D399;
#         border: 1px solid rgba(5, 150, 105, 0.25);
#     }

#     .status-pending {
#         background: rgba(100, 116, 139, 0.1);
#         color: #64748B;
#         border: 1px solid rgba(100, 116, 139, 0.2);
#     }

#     .status-active {
#         background: rgba(99, 102, 241, 0.12);
#         color: #A5B4FC;
#         border: 1px solid rgba(99, 102, 241, 0.25);
#     }

#     /* ── List items ──────────────────────────────────────────────── */
#     .requirement-item {
#         background: rgba(99, 102, 241, 0.06);
#         border-left: 2px solid #6366F1;
#         padding: 0.5rem 0.9rem;
#         border-radius: 0 8px 8px 0;
#         margin-bottom: 0.4rem;
#         font-size: 0.88rem;
#         color: #CBD5E1;
#         line-height: 1.5;
#     }

#     .pain-item {
#         background: rgba(244, 63, 94, 0.06);
#         border-left: 2px solid #F43F5E;
#         padding: 0.5rem 0.9rem;
#         border-radius: 0 8px 8px 0;
#         margin-bottom: 0.4rem;
#         font-size: 0.88rem;
#         color: #CBD5E1;
#         line-height: 1.5;
#     }

#     .goal-item {
#         background: rgba(16, 185, 129, 0.06);
#         border-left: 2px solid #10B981;
#         padding: 0.5rem 0.9rem;
#         border-radius: 0 8px 8px 0;
#         margin-bottom: 0.4rem;
#         font-size: 0.88rem;
#         color: #CBD5E1;
#         line-height: 1.5;
#     }

#     .constraint-item {
#         background: rgba(245, 158, 11, 0.06);
#         border-left: 2px solid #F59E0B;
#         padding: 0.5rem 0.9rem;
#         border-radius: 0 8px 8px 0;
#         margin-bottom: 0.4rem;
#         font-size: 0.88rem;
#         color: #CBD5E1;
#         line-height: 1.5;
#     }

#     /* ── Metric cards ────────────────────────────────────────────── */
#     .metric-card {
#         background: rgba(255, 255, 255, 0.03);
#         border: 1px solid rgba(255, 255, 255, 0.07);
#         border-radius: 10px;
#         padding: 0.9rem 1.1rem;
#         margin-bottom: 0.5rem;
#     }

#     .metric-label {
#         font-size: 0.68rem;
#         color: #475569;
#         text-transform: uppercase;
#         letter-spacing: 0.1em;
#         font-weight: 700;
#         margin-bottom: 0.45rem;
#     }

#     .level-badge {
#         display: inline-block;
#         padding: 0.35rem 0.75rem;
#         border-radius: 6px;
#         font-size: 0.9rem;
#         font-weight: 600;
#         background: rgba(255, 255, 255, 0.05);
#         border: 1px solid rgba(255, 255, 255, 0.09);
#         color: #E2E8F0;
#     }

#     /* ── Inputs ──────────────────────────────────────────────────── */
#     div[data-baseweb="input"] { border-radius: 8px !important; }
#     div[data-baseweb="input"] input {
#         padding: 0.45rem 0.75rem !important;
#         font-size: 0.875rem !important;
#         height: auto !important;
#     }
#     div[data-baseweb="textarea"] > div { border-radius: 8px !important; }
#     div[data-baseweb="textarea"] textarea {
#         font-size: 0.875rem !important;
#         line-height: 1.5 !important;
#     }
#     /* Tighter label spacing */
#     label[data-testid="stWidgetLabel"] {
#         font-size: 0.8rem !important;
#         font-weight: 500 !important;
#         color: #64748B !important;
#         margin-bottom: 0.2rem !important;
#     }

#     /* ── Primary buttons ─────────────────────────────────────────── */
#     button[kind="primary"] {
#         background: #6366F1 !important;
#         border: none !important;
#         color: white !important;
#         font-weight: 600 !important;
#         border-radius: 8px !important;
#         font-size: 0.82rem !important;
#         padding: 0.4rem 1rem !important;
#         letter-spacing: 0.01em !important;
#         transition: all 0.18s ease !important;
#         height: auto !important;
#         min-height: 36px !important;
#     }

#     button[kind="primary"]:hover {
#         background: #4F46E5 !important;
#         box-shadow: 0 4px 14px rgba(99, 102, 241, 0.38) !important;
#         transform: translateY(-1px) !important;
#     }

#     /* Secondary / outline buttons */
#     button[kind="secondary"] {
#         border-radius: 8px !important;
#         font-size: 0.82rem !important;
#         padding: 0.4rem 1rem !important;
#         height: auto !important;
#         min-height: 36px !important;
#         font-weight: 500 !important;
#         border: 1px solid rgba(255,255,255,0.12) !important;
#         background: transparent !important;
#         color: #94A3B8 !important;
#         transition: all 0.15s ease !important;
#     }

#     button[kind="secondary"]:hover {
#         border-color: rgba(99,102,241,0.4) !important;
#         color: #A5B4FC !important;
#         background: rgba(99,102,241,0.07) !important;
#     }

#     /* ── Sidebar ─────────────────────────────────────────────────── */
#     [data-testid="stSidebar"] {
#         background: #0D1017 !important;
#         border-right: 1px solid rgba(255, 255, 255, 0.055) !important;
#     }

#     [data-testid="stSidebar"] section[data-testid="stSidebarContent"] {
#         padding-top: 1.5rem !important;
#     }

#     /* ── Download row ────────────────────────────────────────────── */
#     .download-row {
#         display: grid;
#         gap: 0.75rem;
#     }

#     /* ── Section info note ───────────────────────────────────────── */
#     .info-note {
#         background: rgba(99, 102, 241, 0.07);
#         border: 1px solid rgba(99, 102, 241, 0.18);
#         border-radius: 8px;
#         padding: 0.65rem 1rem;
#         font-size: 0.85rem;
#         color: #94A3B8;
#         margin-bottom: 1rem;
#     }

#     /* Tighter file uploader */
#     [data-testid="stFileUploader"] { margin-bottom: 0.5rem !important; }
#     [data-testid="stFileUploader"] label { font-size: 0.82rem !important; color: #64748B !important; }

#     /* ══════════════════════════════════════════════════════════
#        LIGHT THEME — activated when html[data-theme="light"]
#        ══════════════════════════════════════════════════════════ */

#     /* App background */
#     html[data-theme="light"] .stApp,
#     html[data-theme="light"] [data-testid="stAppViewContainer"],
#     html[data-theme="light"] [data-testid="stMain"],
#     html[data-theme="light"] section.main,
#     html[data-theme="light"] .main .block-container {
#         background: #F1F5F9 !important;
#         color: #1E293B !important;
#     }

#     /* Sidebar */
#     html[data-theme="light"] [data-testid="stSidebar"] {
#         background: #FFFFFF !important;
#         border-right: 1px solid rgba(0,0,0,0.09) !important;
#     }
#     html[data-theme="light"] [data-testid="stSidebar"] label,
#     html[data-theme="light"] [data-testid="stSidebar"] span,
#     html[data-theme="light"] [data-testid="stSidebar"] p,
#     html[data-theme="light"] [data-testid="stSidebarContent"] div { color: #475569 !important; }
#     html[data-theme="light"] [data-testid="stSidebar"] select,
#     html[data-theme="light"] [data-testid="stSidebar"] input { background: #F8FAFC !important; color: #1E293B !important; }

#     /* Typography */
#     html[data-theme="light"] .main-title { color: #0F172A !important; }
#     html[data-theme="light"] .subtitle { color: #64748B !important; }

#     /* Markdown text */
#     html[data-theme="light"] [data-testid="stMarkdownContainer"] p,
#     html[data-theme="light"] [data-testid="stMarkdownContainer"] li,
#     html[data-theme="light"] [data-testid="stMarkdownContainer"] strong { color: #334155 !important; }
#     html[data-theme="light"] [data-testid="stMarkdownContainer"] h1,
#     html[data-theme="light"] [data-testid="stMarkdownContainer"] h2,
#     html[data-theme="light"] [data-testid="stMarkdownContainer"] h3,
#     html[data-theme="light"] [data-testid="stMarkdownContainer"] h4 { color: #0F172A !important; }

#     /* Accent bars: keep colors, just adjust opacity */
#     html[data-theme="light"] .accent-bar,
#     html[data-theme="light"] .accent-bar-purple,
#     html[data-theme="light"] .accent-bar-green { opacity: 0.7; }

#     /* Metric & glass cards */
#     html[data-theme="light"] .metric-card {
#         background: rgba(255,255,255,0.9) !important;
#         border-color: rgba(0,0,0,0.09) !important;
#     }
#     html[data-theme="light"] .metric-label { color: #64748B !important; }
#     html[data-theme="light"] .level-badge {
#         background: rgba(0,0,0,0.05) !important;
#         border-color: rgba(0,0,0,0.1) !important;
#         color: #1E293B !important;
#     }

#     /* List items */
#     html[data-theme="light"] .requirement-item {
#         background: rgba(99,102,241,0.07) !important;
#         color: #1E293B !important;
#         border-left-color: #6366F1 !important;
#     }
#     html[data-theme="light"] .pain-item {
#         background: rgba(244,63,94,0.06) !important;
#         color: #1E293B !important;
#     }
#     html[data-theme="light"] .goal-item {
#         background: rgba(16,185,129,0.07) !important;
#         color: #1E293B !important;
#     }
#     html[data-theme="light"] .constraint-item {
#         background: rgba(245,158,11,0.07) !important;
#         color: #1E293B !important;
#     }

#     /* Inputs & textareas */
#     html[data-theme="light"] div[data-baseweb="input"] div,
#     html[data-theme="light"] div[data-baseweb="input"] { background: #FFFFFF !important; border-color: rgba(0,0,0,0.12) !important; }
#     html[data-theme="light"] div[data-baseweb="input"] input { color: #0F172A !important; background: transparent !important; }
#     html[data-theme="light"] div[data-baseweb="textarea"] > div { background: #FFFFFF !important; border-color: rgba(0,0,0,0.12) !important; }
#     html[data-theme="light"] div[data-baseweb="textarea"] textarea { color: #0F172A !important; }
#     html[data-theme="light"] label[data-testid="stWidgetLabel"] { color: #475569 !important; }

#     /* Buttons: primary stays indigo, secondary gets light border */
#     html[data-theme="light"] button[kind="secondary"] {
#         border-color: rgba(0,0,0,0.15) !important;
#         color: #475569 !important;
#         background: rgba(0,0,0,0.03) !important;
#     }
#     html[data-theme="light"] button[kind="secondary"]:hover {
#         border-color: rgba(99,102,241,0.4) !important;
#         color: #6366F1 !important;
#         background: rgba(99,102,241,0.06) !important;
#     }

#     /* Toggle */
#     html[data-theme="light"] [data-testid="stToggle"] span { border-color: rgba(0,0,0,0.2) !important; }

#     /* Alerts & info boxes */
#     html[data-theme="light"] [data-testid="stAlert"] { background: rgba(99,102,241,0.07) !important; }
#     html[data-theme="light"] [data-testid="stAlert"] div { color: #334155 !important; }

#     /* Expanders */
#     html[data-theme="light"] [data-testid="stExpander"] { border-color: rgba(0,0,0,0.1) !important; }
#     html[data-theme="light"] [data-testid="stExpander"] summary { color: #334155 !important; }

#     /* Code blocks */
#     html[data-theme="light"] code { background: rgba(0,0,0,0.05) !important; color: #1E293B !important; }
#     html[data-theme="light"] pre code { background: rgba(0,0,0,0.04) !important; }

#     /* Tabs */
#     html[data-theme="light"] [data-testid="stTabs"] [role="tab"] { color: #64748B !important; }
#     html[data-theme="light"] [data-testid="stTabs"] [role="tab"][aria-selected="true"] { color: #6366F1 !important; }

#     /* DataFrames */
#     html[data-theme="light"] [data-testid="stDataFrame"] { background: #FFFFFF !important; }

#     /* Caption & small text */
#     html[data-theme="light"] [data-testid="stCaptionContainer"] p { color: #64748B !important; }

#     /* Selectbox */
#     html[data-theme="light"] div[data-baseweb="select"] > div { background: #FFFFFF !important; border-color: rgba(0,0,0,0.12) !important; color: #1E293B !important; }

#     /* File uploader */
#     html[data-theme="light"] [data-testid="stFileUploader"] { background: rgba(0,0,0,0.02) !important; border-color: rgba(0,0,0,0.1) !important; }
#     html[data-theme="light"] [data-testid="stFileUploader"] label { color: #475569 !important; }

#     /* Status badges override for light */
#     html[data-theme="light"] .status-completed { background: rgba(5,150,105,0.08) !important; color: #059669 !important; border-color: rgba(5,150,105,0.2) !important; }
#     html[data-theme="light"] .status-pending { background: rgba(100,116,139,0.08) !important; color: #475569 !important; }
#     html[data-theme="light"] .status-active { background: rgba(99,102,241,0.08) !important; color: #6366F1 !important; }

#     /* ══════════════════════════════════════════════════════════
#        SYSTEM THEME — prefers-color-scheme media queries
#        Only active when html has no data-theme or data-theme="system"
#        ══════════════════════════════════════════════════════════ */
#     @media (prefers-color-scheme: light) {
#         html:not([data-theme="dark"]):not([data-theme="light"]) .stApp { background: #F1F5F9 !important; }
#         html:not([data-theme="dark"]):not([data-theme="light"]) [data-testid="stSidebar"] { background: #FFFFFF !important; }
#     }
# </style>
# """, unsafe_allow_html=True)
 
# # -------------------------------------------------------------
# # Theme applicator — injects JS to set data-theme on <html>
# # -------------------------------------------------------------
# def _apply_theme(theme: str) -> None:
#     """Apply dark/light/system theme by setting data-theme attr on the parent document's <html>."""
#     js = (
#         "(function(){{"
#         "var t='{t}',r=t;"
#         "if(t==='system'){{r=window.matchMedia('(prefers-color-scheme:dark)').matches?'dark':'light';}}"
#         "var d=window.parent?window.parent.document:document;"
#         "d.documentElement.setAttribute('data-theme',r);"
#         "if(t==='system'){{"
#         "window.matchMedia('(prefers-color-scheme:dark)').addEventListener('change',function(e){{"
#         "d.documentElement.setAttribute('data-theme',e.matches?'dark':'light');}})"
#         "}}"
#         "}})();"
#     ).format(t=theme)
#     components.html(f"<script>{js}</script>", height=0, scrolling=False)


# # -------------------------------------------------------------
# # Session State Initialization
# # -------------------------------------------------------------
# if "user" not in st.session_state:
#     st.session_state.user = None
# if "app_theme" not in st.session_state:
#     st.session_state.app_theme = "dark"
# if "selected_project" not in st.session_state:
#     st.session_state.selected_project = None
# if "auth_mode" not in st.session_state:
#     st.session_state.auth_mode = "login"
# if "task_output" not in st.session_state:
#     st.session_state.task_output = None
# if "approved_requirements" not in st.session_state:
#     st.session_state.approved_requirements = None
# if "plan_output" not in st.session_state:
#     st.session_state.plan_output = None
# if "feasibility_output" not in st.session_state:
#     st.session_state.feasibility_output = None
# if "approved_plan" not in st.session_state:
#     st.session_state.approved_plan = None
# if "estimation_output" not in st.session_state:
#     st.session_state.estimation_output = None
# if "approved_estimation" not in st.session_state:
#     st.session_state.approved_estimation = None
# if "approved_feasibility" not in st.session_state:
#     st.session_state.approved_feasibility = None
# if "approved_plan" not in st.session_state:
#     st.session_state.approved_plan = None
# if "report_output" not in st.session_state:
#     st.session_state.report_output = None


# def reset_planning_pipeline():
#     st.session_state.plan_output = None
#     st.session_state.feasibility_output = None
#     st.session_state.approved_plan = None
#     st.session_state.approved_feasibility = None
#     st.session_state.estimation_output = None
#     st.session_state.approved_estimation = None
#     st.session_state.report_output = None
#     st.session_state.pop("hitl2_edit_mode", None)
#     st.session_state.pop("hitl_est_edit_mode", None)
#     st.session_state.pop("hitl2_plan_edit", None)
#     st.session_state.pop("hitl2_feas_edit", None)
#     st.session_state.pop("hitl2_est_edit", None)
 
# # -------------------------------------------------------------
# # Authentication Screen
# # -------------------------------------------------------------
# def render_auth_page():
#     # Apply current theme
#     _apply_theme(st.session_state.get("app_theme", "dark"))

#     # Small theme toggle top-right
#     _spacer, _th_col = st.columns([5, 1])
#     with _th_col:
#         _t = st.session_state.get("app_theme", "dark")
#         _icons = {"dark": "🌙", "light": "☀️", "system": "💻"}
#         _cycle = {"dark": "light", "light": "system", "system": "dark"}
#         if st.button(_icons[_t], key="auth_theme_cycle", help="Toggle theme"):
#             st.session_state.app_theme = _cycle[_t]
#             st.rerun()

#     # Full-page centering spacer
#     st.markdown('<div style="height:1.5rem"></div>', unsafe_allow_html=True)

#     col1, col2, col3 = st.columns([1, 1.35, 1])

#     with col2:
#         # ── Brand header (pure HTML — no widgets, so no empty-box issue) ──
#         is_login = st.session_state.auth_mode == "login"
#         mode_title = "Sign In" if is_login else "Create Account"
#         mode_sub   = "Welcome back — sign in to continue." if is_login else "Create your account to get started."

#         st.markdown(
#             f'<div style="text-align:center;padding:1.75rem 0 1.25rem">'
#             f'<div style="display:inline-flex;align-items:center;justify-content:center;'
#             f'width:46px;height:46px;border-radius:12px;'
#             f'background:rgba(99,102,241,0.15);border:1px solid rgba(99,102,241,0.3);'
#             f'font-size:1.3rem;margin-bottom:0.65rem">⚡</div>'
#             f'<div style="font-size:0.72rem;font-weight:700;text-transform:uppercase;'
#             f'letter-spacing:0.12em;color:#475569;margin-bottom:0.35rem">AI-Powered POC Generator</div>'
#             f'<div style="font-size:1.45rem;font-weight:700;color:#E2E8F0;letter-spacing:-0.4px;'
#             f'line-height:1.2;margin-bottom:0.3rem">{mode_title}</div>'
#             f'<div style="font-size:0.8rem;color:#475569">{mode_sub}</div>'
#             f'</div>'
#             f'<div style="height:1px;background:linear-gradient(90deg,transparent,'
#             f'rgba(99,102,241,0.5),transparent);margin-bottom:1.4rem"></div>',
#             unsafe_allow_html=True,
#         )

#         # ── Form widgets render naturally — no wrapping div ───────────────
#         if is_login:
#             email    = st.text_input("Email Address", placeholder="name@company.com", key="login_email")
#             password = st.text_input("Password", type="password", placeholder="••••••••", key="login_password")

#             st.markdown('<div style="height:0.35rem"></div>', unsafe_allow_html=True)

#             if st.button("Sign In", type="primary", use_container_width=True, key="login_btn"):
#                 if not email or not password:
#                     st.error("Please fill in all fields.")
#                 else:
#                     try:
#                         res = db.sign_in(email, password)
#                         st.session_state.user = res.user
#                         st.success("Signed in successfully.")
#                         st.rerun()
#                     except Exception as e:
#                         st.error(f"Login failed: {e}")

#             st.markdown(
#                 '<div style="display:flex;align-items:center;gap:0.75rem;margin:1rem 0">'
#                 '<div style="flex:1;height:1px;background:rgba(255,255,255,0.07)"></div>'
#                 '<div style="font-size:0.72rem;color:#334155;white-space:nowrap">or</div>'
#                 '<div style="flex:1;height:1px;background:rgba(255,255,255,0.07)"></div>'
#                 '</div>',
#                 unsafe_allow_html=True,
#             )

#             if st.button("Create an account", use_container_width=True, key="goto_signup"):
#                 st.session_state.auth_mode = "signup"
#                 st.rerun()

#         else:
#             email    = st.text_input("Email Address", placeholder="name@company.com", key="signup_email")
#             password = st.text_input("Password", type="password", placeholder="At least 6 characters", key="signup_password")

#             st.markdown('<div style="height:0.35rem"></div>', unsafe_allow_html=True)

#             if st.button("Create Account", type="primary", use_container_width=True, key="signup_btn"):
#                 if not email or not password:
#                     st.error("Please fill in all fields.")
#                 elif len(password) < 6:
#                     st.error("Password must be at least 6 characters.")
#                 else:
#                     try:
#                         db.sign_up(email, password)
#                         st.success("Account created! Please sign in.")
#                         st.session_state.auth_mode = "login"
#                         st.rerun()
#                     except Exception as e:
#                         st.error(f"Sign up failed: {e}")

#             st.markdown(
#                 '<div style="display:flex;align-items:center;gap:0.75rem;margin:1rem 0">'
#                 '<div style="flex:1;height:1px;background:rgba(255,255,255,0.07)"></div>'
#                 '<div style="font-size:0.72rem;color:#334155;white-space:nowrap">or</div>'
#                 '<div style="flex:1;height:1px;background:rgba(255,255,255,0.07)"></div>'
#                 '</div>',
#                 unsafe_allow_html=True,
#             )

#             if st.button("Already have an account? Sign In", use_container_width=True, key="goto_login"):
#                 st.session_state.auth_mode = "login"
#                 st.rerun()

#         # ── Footer note ────────────────────────────────────────────────────
#         st.markdown(
#             '<div style="text-align:center;margin-top:1.5rem;font-size:0.72rem;color:#1E293B">'
#             'Powered by Gemini AI &nbsp;·&nbsp; Secured by Supabase'
#             '</div>',
#             unsafe_allow_html=True,
#         )
 
# # -------------------------------------------------------------
# # Render Task Agent Results (HITL)
# # -------------------------------------------------------------
# def render_task_agent_section(transcript: str, project_id: str):
#     st.markdown(
#         '<div class="accent-bar-green"></div>'
#         + _step_header("2", "Task Identification Agent",
#             "Extract requirements, pain points, constraints & business goals from the transcript",
#             "green"),
#         unsafe_allow_html=True,
#     )
 
#     col_run, col_status = st.columns([2, 1])
 
#     with col_run:
#         st.markdown("**Run the Task Agent** to extract requirements, pain points, constraints, and business goals from your transcript using Gemini AI.")
 
#     with col_status:
#         if st.session_state.task_output:
#             st.markdown("<span class='status-badge status-completed'>✅ COMPLETED</span>", unsafe_allow_html=True)
#         else:
#             st.markdown("<span class='status-badge status-pending'>PENDING</span>", unsafe_allow_html=True)
 
#     col_btn1, col_btn2 = st.columns([1, 3])
#     with col_btn1:
#         run_clicked = st.button("▶ Run Task Agent", type="primary", key="run_task_agent_btn")
 
#     if run_clicked:
#         with st.spinner("🤖 Gemini is analyzing the transcript..."):
#             try:
#                 result = call_task_agent(transcript)
#                 st.session_state.task_output = result
#                 st.session_state.approved_requirements = None
#                 reset_planning_pipeline()
#                 st.success("✅ Task Agent completed successfully!")
#                 st.rerun()
#             except Exception as e:
#                 st.error(f"Task Agent failed: {e}")
 
#     # Display results if available
#     if st.session_state.task_output:
#         output = st.session_state.task_output
 
#         st.markdown("#### 📋 Extracted Requirements — Please Review")
        
#         tab1, tab2, tab3, tab4, tab5 = st.tabs(["🔴 Pain Points", "✅ Requirements", "⚠️ Constraints", "🎯 Business Goals", "💻 Tech Context"])
        
#         with tab1:
#             if output.pain_points:
#                 for item in output.pain_points:
#                     st.markdown(f'<div class="pain-item">• {item}</div>', unsafe_allow_html=True)
#             else:
#                 st.info("No pain points identified.")
        
#         with tab2:
#             if output.requirements:
#                 for item in output.requirements:
#                     st.markdown(f'<div class="requirement-item">• {item}</div>', unsafe_allow_html=True)
#             else:
#                 st.info("No requirements identified.")
        
#         with tab3:
#             if output.constraints:
#                 for item in output.constraints:
#                     st.markdown(f'<div class="constraint-item">• {item}</div>', unsafe_allow_html=True)
#             else:
#                 st.info("No constraints identified.")
        
#         with tab4:
#             if output.business_goals:
#                 for item in output.business_goals:
#                     st.markdown(f'<div class="goal-item">• {item}</div>', unsafe_allow_html=True)
#             else:
#                 st.info("No business goals identified.")
        
#         with tab5:
#             tech_ctx = getattr(output, 'technology_context', {}) or {}
#             if tech_ctx:
#                 for category, description in tech_ctx.items():
#                     label = category.replace("_", " ").title()
#                     st.markdown(f'<div class="requirement-item"><strong>{label}:</strong> {description}</div>', unsafe_allow_html=True)
#             else:
#                 st.info("No technology context identified.")
 
#         # ---------------------------------------------------------
#         # HITL Actions
#         # ---------------------------------------------------------
#         st.markdown("---")
#         st.markdown("#### 🧑‍💼 Human-in-the-Loop Review")
#         st.markdown("Review the extracted requirements above and choose an action:")

#         hitl1_feedback = st.text_area(
#             "💬 What would you like to change? (optional — leave blank to regenerate as-is)",
#             placeholder="e.g. 'The budget constraint of $50k was missed', 'Add mobile app requirement', 'Constraints section needs more detail'",
#             height=80,
#             key="hitl1_feedback",
#         )

#         hitl_col1, hitl_col2, _ = st.columns([1, 1, 2])

#         with hitl_col1:
#             if st.button("✅ Approve & Auto-Run", type="primary", use_container_width=True, key="approve_btn"):
#                 st.session_state.approved_requirements = output.model_dump()
#                 reset_planning_pipeline()
#                 _pid = (st.session_state.selected_project or {}).get("id")

#                 # ── Auto-run Planning Agent ────────────────────────────────
#                 _plan_ok = False
#                 with st.spinner("🏗️ Running Planning Agent…"):
#                     try:
#                         _plan_result = call_planning_agent(st.session_state.approved_requirements, project_id=_pid)
#                         st.session_state.plan_output = _plan_result
#                         _plan_ok = True
#                     except Exception as _e:
#                         st.error(f"Planning Agent failed: {_e}")

#                 # ── Auto-run Feasibility Agent (only if planning succeeded) ─
#                 if _plan_ok:
#                     with st.spinner("🔍 Running Feasibility Agent…"):
#                         try:
#                             _feas_result = call_feasibility_agent(
#                                 st.session_state.approved_requirements,
#                                 _plan_result.model_dump(),
#                             )
#                             st.session_state.feasibility_output = _feas_result
#                             st.success("✅ Requirements approved — architecture & feasibility ready for review.")
#                         except Exception as _e:
#                             st.error(f"Feasibility Agent failed: {_e}")

#                 st.rerun()

#         with hitl_col2:
#             if st.button("🔄 Regenerate", use_container_width=True, key="regen_btn"):
#                 with st.spinner("🤖 Regenerating..."):
#                     try:
#                         result = call_task_agent(transcript, feedback=hitl1_feedback)
#                         st.session_state.task_output = result
#                         st.session_state.approved_requirements = None
#                         reset_planning_pipeline()
#                         st.rerun()
#                     except Exception as e:
#                         st.error(f"Regeneration failed: {e}")

#         # Show approved confirmation
#         if st.session_state.approved_requirements and st.session_state.plan_output and st.session_state.feasibility_output:
#             st.success("🎉 Requirements approved — Planning and Feasibility complete. Review them below then approve.")

#     st.markdown('<div style="height:0.5rem"></div>', unsafe_allow_html=True)


# # -------------------------------------------------------------
# # Render Planning Agent Results
# # -------------------------------------------------------------
# def render_planning_agent_section():
#     st.markdown(
#         '<div class="accent-bar-purple"></div>'
#         + _step_header("3", "Planning Agent",
#             "Generate technical architecture, tech stack & system diagram from approved requirements",
#             "violet"),
#         unsafe_allow_html=True,
#     )

#     col_run, col_status = st.columns([2, 1])

#     with col_run:
#         if st.session_state.plan_output:
#             st.markdown("Architecture generated automatically after HITL #1 approval. Re-run to regenerate.")
#         else:
#             st.markdown("Runs automatically when you approve HITL #1. You can also trigger it manually.")

#     with col_status:
#         if st.session_state.plan_output:
#             st.markdown("<span class='status-badge status-completed'>✅ COMPLETED</span>", unsafe_allow_html=True)
#         else:
#             st.markdown("<span class='status-badge status-pending'>AUTO / MANUAL</span>", unsafe_allow_html=True)

#     _plan_btn_col, _ = st.columns([1, 3])
#     with _plan_btn_col:
#         _plan_label = "🔄 Re-run Planning Agent" if st.session_state.plan_output else "▶ Run Planning Agent"
#         if st.button(_plan_label, type="primary" if not st.session_state.plan_output else "secondary",
#                      key="run_planning_agent_btn", use_container_width=True):
#             with st.spinner("🏗️ Gemini is designing the architecture..."):
#                 try:
#                     _pid = (st.session_state.selected_project or {}).get("id")
#                     result = call_planning_agent(st.session_state.approved_requirements, project_id=_pid)
#                     st.session_state.plan_output = result
#                     st.session_state.feasibility_output = None
#                     st.session_state.approved_plan = None
#                     st.success("✅ Planning Agent completed successfully!")
#                     st.rerun()
#                 except Exception as e:
#                     st.error(f"Planning Agent failed: {e}")

#     if st.session_state.plan_output:
#         plan = st.session_state.plan_output

#         st.markdown(f"#### 🧩 Architecture: **{plan.architecture_type}**")

#         if plan.tech_stack:
#             st.markdown("##### 🛠️ Tech Stack")
#             for category, tech in plan.tech_stack.items():
#                 reason = plan.recommendation_reason.get(category, "")
#                 label = category.replace("_", " ").title()
#                 st.markdown(f"**{label}:** {tech}")
#                 if reason:
#                     st.caption(reason)

#         summary = plan.architecture_summary
#         st.markdown("##### 📐 Architecture Summary")
#         st.markdown(f"**Overview:** {summary.overview}")
#         st.markdown(f"**Workflow:** {summary.workflow}")
#         st.markdown(f"**Data Flow:** {summary.data_flow}")

#         if plan.reference_docs:
#             st.markdown("##### 📚 Reference Docs")
#             for doc in plan.reference_docs:
#                 st.markdown(f"- [{doc.title}]({doc.url})")

#         if plan.mermaid_diagram:
#             st.markdown("##### 🗺️ Architecture Diagram")
#             with st.expander("📊 View Architecture Diagram", expanded=True):
#                 render_mermaid_diagram(plan.mermaid_diagram)
#             with st.expander("📝 Diagram Source (Mermaid)", expanded=False):
#                 st.code(plan.mermaid_diagram, language="mermaid")

#     st.markdown('<div style="height:0.5rem"></div>', unsafe_allow_html=True)


# # -------------------------------------------------------------
# # Render Feasibility Agent + HITL #2
# # -------------------------------------------------------------
# def render_feasibility_section():
#     st.markdown(
#         '<div class="accent-bar"></div>'
#         + _step_header("4", "Feasibility Study",
#             "Evaluate technical risks, complexity & viability of the proposed architecture",
#             "indigo"),
#         unsafe_allow_html=True,
#     )

#     col_run, col_status = st.columns([2, 1])

#     with col_run:
#         if st.session_state.feasibility_output:
#             st.markdown("Feasibility generated automatically after HITL #1 approval. Re-run to regenerate.")
#         else:
#             st.markdown("Runs automatically after Planning Agent. You can also trigger it manually.")

#     with col_status:
#         if st.session_state.feasibility_output:
#             st.markdown("<span class='status-badge status-completed'>✅ COMPLETED</span>", unsafe_allow_html=True)
#         else:
#             st.markdown("<span class='status-badge status-pending'>AUTO / MANUAL</span>", unsafe_allow_html=True)

#     _feas_btn_col, _ = st.columns([1, 3])
#     with _feas_btn_col:
#         _feas_label = "🔄 Re-run Feasibility Agent" if st.session_state.feasibility_output else "▶ Run Feasibility Agent"
#         if st.button(_feas_label, type="primary" if not st.session_state.feasibility_output else "secondary",
#                      key="run_feasibility_agent_btn", use_container_width=True):
#             with st.spinner("🔍 Gemini is assessing feasibility..."):
#                 try:
#                     result = call_feasibility_agent(
#                         st.session_state.approved_requirements,
#                         st.session_state.plan_output.model_dump(),
#                     )
#                     st.session_state.feasibility_output = result
#                     st.session_state.approved_plan = None
#                     st.success("✅ Feasibility Agent completed successfully!")
#                     st.rerun()
#                 except Exception as e:
#                     st.error(f"Feasibility Agent failed: {e}")

#     if st.session_state.feasibility_output:
#         feasibility = st.session_state.feasibility_output

#         st.markdown("#### 📊 Feasibility Assessment")

#         metric_col1, metric_col2, metric_col3 = st.columns(3)
#         with metric_col1:
#             st.markdown('<div class="metric-card">', unsafe_allow_html=True)
#             st.markdown('<div class="metric-label">Complexity</div>', unsafe_allow_html=True)
#             st.markdown(
#                 level_badge_html(feasibility.complexity_level, COMPLEXITY_BADGES),
#                 unsafe_allow_html=True,
#             )
#             st.markdown('</div>', unsafe_allow_html=True)
#         arch_confidence = getattr(feasibility, "architecture_confidence", None)
#         feas_confidence = getattr(feasibility, "feasibility_confidence", None)

#         with metric_col2:
#             st.markdown('<div class="metric-card">', unsafe_allow_html=True)
#             st.markdown('<div class="metric-label">Architecture Confidence</div>', unsafe_allow_html=True)
#             if arch_confidence:
#                 st.markdown(level_badge_html(arch_confidence, CONFIDENCE_BADGES), unsafe_allow_html=True)
#             else:
#                 st.caption("Re-run agent to refresh")
#             st.markdown('</div>', unsafe_allow_html=True)
#         with metric_col3:
#             st.markdown('<div class="metric-card">', unsafe_allow_html=True)
#             st.markdown('<div class="metric-label">Feasibility Confidence</div>', unsafe_allow_html=True)
#             if feas_confidence:
#                 st.markdown(level_badge_html(feas_confidence, CONFIDENCE_BADGES), unsafe_allow_html=True)
#             else:
#                 st.caption("Re-run agent to refresh")
#             st.markdown('</div>', unsafe_allow_html=True)

#         st.markdown(f"**Summary:** {feasibility.feasibility_summary}")

#         if feasibility.technical_risks:
#             st.markdown("##### ⚠️ Technical Risks")
#             for risk in feasibility.technical_risks:
#                 with st.expander(f"🔴 {risk.risk}", expanded=False):
#                     st.markdown(f"**Impact:** {risk.impact}")
#                     st.markdown(f"**Mitigation:** {risk.mitigation}")
#         else:
#             st.info("No technical risks identified.")

#     st.markdown('<div style="height:0.5rem"></div>', unsafe_allow_html=True)


# # -------------------------------------------------------------
# # Shared helper — build estimation DataFrame from raw list + columns
# # -------------------------------------------------------------
# def _build_estimation_df(
#     estimations: list,
#     structural_cols: list,
#     tech_cols: list,
#     include_mvp: bool = False,
#     totals=None,
# ) -> pd.DataFrame:
#     rows = []
#     for item in estimations:
#         # Normalise to dict — handles both Pydantic objects and plain dicts
#         data = item if isinstance(item, dict) else item.model_dump(warnings=False)
#         row = {col: data.get(col, "") for col in structural_cols}
#         tech_hours = data.get("tech_hours") or {}
#         for col in tech_cols:
#             row[f"{col} (hrs)"] = tech_hours.get(col, 0)
#         row["Remarks - Tech Team"] = data.get("tech_remarks", "")
#         row["Remarks - BA Team"] = data.get("ba_remarks", "")
#         if include_mvp and data.get("phase"):
#             row["Phase"] = data.get("phase", "")
#         rows.append(row)

#     if totals is not None:
#         t = totals if isinstance(totals, dict) else totals.model_dump(warnings=False)
#         t_total = t.get("total_hours", 0)
#         t_tech  = t.get("tech_breakdown") or {}
#         totals_row = {col: "" for col in structural_cols}
#         # Put "TOTALS" label in the second structural column (first is usually "No")
#         if len(structural_cols) > 1:
#             totals_row[structural_cols[1]] = "TOTALS"
#         for col in tech_cols:
#             totals_row[f"{col} (hrs)"] = t_tech.get(col, 0)
#         totals_row["Remarks - Tech Team"] = f"Grand Total: {t_total} hrs"
#         totals_row["Remarks - BA Team"] = ""
#         if include_mvp:
#             p1, p2 = t.get("phase1_hours"), t.get("phase2_hours")
#             if p1 is not None:
#                 totals_row["Phase"] = f"MVP: {p1} hrs | Full Build: {p2} hrs"
#         rows.append(totals_row)

#     return pd.DataFrame(rows)


# def _estimation_col_config(structural_cols: list, tech_cols: list, include_mvp: bool = False) -> dict:
#     cfg = {}
#     for i, col in enumerate(structural_cols):
#         # Heuristic widths: first col (No/ID) small, description cols large, others medium
#         col_lower = col.lower()
#         if i == 0 or col_lower in ("no", "id", "#"):
#             width = "small"
#         elif any(k in col_lower for k in ("feature", "description", "task", "detail")):
#             width = "large"
#         elif any(k in col_lower for k in ("complexity", "layer", "platform", "type", "interface")):
#             width = "small"
#         else:
#             width = "medium"
#         cfg[col] = st.column_config.TextColumn(col, width=width)
#     for col in tech_cols:
#         cfg[f"{col} (hrs)"] = st.column_config.NumberColumn(f"{col} (hrs)", width="small")
#     cfg["Remarks - Tech Team"] = st.column_config.TextColumn("Remarks - Tech Team", width="large")
#     cfg["Remarks - BA Team"]   = st.column_config.TextColumn("Remarks - BA Team", width="medium")
#     if include_mvp:
#         cfg["Phase"] = st.column_config.TextColumn("Phase", width="medium")
#     return cfg


# # -------------------------------------------------------------
# # Render Estimation Agent Results + HITL
# # -------------------------------------------------------------
# def render_estimation_section():
#     st.markdown(
#         '<div class="accent-bar-green"></div>'
#         + _step_header("5", "Effort Estimation",
#             "Generate Work Breakdown Structure with per-module, per-role hour estimates",
#             "green"),
#         unsafe_allow_html=True,
#     )

#     col_run, col_status = st.columns([2, 1])

#     with col_run:
#         st.markdown(
#             "**Run the Estimation Agent** to generate a detailed Work Breakdown Structure (WBS) "
#             "with effort estimates broken down by module, feature, task, and engineering role."
#         )

#     with col_status:
#         if st.session_state.estimation_output:
#             st.markdown("<span class='status-badge status-completed'>✅ COMPLETED</span>", unsafe_allow_html=True)
#         else:
#             st.markdown("<span class='status-badge status-pending'>PENDING</span>", unsafe_allow_html=True)

#     include_mvp = st.toggle(
#         "Include MVP / Full Build phase split",
#         value=st.session_state.get("include_mvp", False),
#         key="include_mvp_toggle",
#         help="When enabled, tasks are split into MVP (minimum viable product) and Full Build phases.",
#     )
#     st.session_state["include_mvp"] = include_mvp

#     if st.button("▶ Run Estimation Agent", type="primary", key="run_estimation_agent_btn"):
#         with st.spinner("📊 Generating Work Breakdown Structure..."):
#             try:
#                 _pid = (st.session_state.selected_project or {}).get("id")
#                 result = call_estimation_agent(
#                     st.session_state.approved_requirements,
#                     st.session_state.plan_output.model_dump(),
#                     st.session_state.feasibility_output.model_dump(),
#                     project_id=_pid,
#                     transcript=st.session_state.get("current_transcript", ""),
#                     include_mvp=include_mvp,
#                 )
#                 st.session_state.estimation_output = result
#                 st.session_state.approved_estimation = None
#                 st.success("✅ Estimation Agent completed successfully!")
#                 st.rerun()
#             except Exception as e:
#                 st.error(f"Estimation Agent failed: {e}")

#     if st.session_state.estimation_output:
#         estimation = st.session_state.estimation_output
#         _include_mvp  = st.session_state.get("include_mvp", False)
#         struct_cols   = estimation.structural_columns or []
#         tech_cols     = estimation.tech_stack_columns or []

#         st.markdown("#### 📋 Effort Estimation Table")

#         df = _build_estimation_df(
#             estimation.estimations, struct_cols, tech_cols,
#             include_mvp=_include_mvp, totals=estimation.totals,
#         )
#         st.dataframe(df, use_container_width=True, hide_index=True,
#                      column_config=_estimation_col_config(struct_cols, tech_cols, _include_mvp))

#         totals = estimation.totals
#         st.markdown(
#             f'<div style="font-size:0.8rem;font-weight:600;color:#94A3B8;margin-bottom:0.6rem">'
#             f'Grand Total: <span style="color:#E2E8F0;font-size:0.95rem">{totals.total_hours} hrs</span></div>',
#             unsafe_allow_html=True,
#         )

#         if totals.tech_breakdown:
#             items = list(totals.tech_breakdown.items())
#             metric_cols = st.columns(min(len(items), 6))
#             for col, (tech, hrs) in zip(metric_cols, items):
#                 with col:
#                     st.markdown(
#                         f'<div style="background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.07);'
#                         f'border-radius:8px;padding:0.45rem 0.6rem;text-align:center;margin-bottom:0.4rem">'
#                         f'<div style="font-size:0.6rem;color:#475569;text-transform:uppercase;letter-spacing:0.08em;'
#                         f'font-weight:700;margin-bottom:0.15rem">{tech}</div>'
#                         f'<div style="font-size:1rem;font-weight:700;color:#E2E8F0;line-height:1">{hrs}'
#                         f'<span style="font-size:0.62rem;color:#475569;margin-left:2px">hrs</span></div>'
#                         f'</div>',
#                         unsafe_allow_html=True,
#                     )

#         if _include_mvp and totals.phase1_hours is not None:
#             st.markdown(
#                 f"MVP: **{totals.phase1_hours} hrs** &nbsp;|&nbsp; Full Build: **{totals.phase2_hours} hrs**",
#                 unsafe_allow_html=True,
#             )

#         buffer = io.BytesIO()
#         with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
#             df.to_excel(writer, index=False, sheet_name="Effort Estimation")
#         buffer.seek(0)

#         st.download_button(
#             label="📥 Download Estimation as Excel",
#             data=buffer,
#             file_name="effort_estimation.xlsx",
#             mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
#             use_container_width=True,
#             key="dl_est_excel",
#         )

#     st.markdown('<div style="height:0.5rem"></div>', unsafe_allow_html=True)


# # -------------------------------------------------------------
# # Unified HITL #2: Review Plan + Feasibility + Estimation
# # -------------------------------------------------------------
# def render_hitl2_section():
#     st.markdown('<div class="accent-bar-green"></div>', unsafe_allow_html=True)

#     st.markdown(
#         "Review and approve **Planning**, **Feasibility**, and **Estimation** outputs before generating the final report."
#     )

#     # Show summary tabs
#     tab_plan, tab_feas, tab_est = st.tabs(["🏗️ Plan", "🔍 Feasibility", "📊 Estimation"])

#     with tab_plan:
#         plan = st.session_state.plan_output
#         st.markdown(f"**Architecture:** {plan.architecture_type}")
#         if plan.tech_stack:
#             st.json(plan.tech_stack)
#         summary = plan.architecture_summary
#         st.markdown(f"**Overview:** {summary.overview}")
#         st.markdown(f"**Workflow:** {summary.workflow}")
#         st.markdown(f"**Data Flow:** {summary.data_flow}")

#     with tab_feas:
#         feas = st.session_state.feasibility_output
#         st.markdown(f"**Complexity:** {feas.complexity_level}")
#         st.markdown(f"**Summary:** {feas.feasibility_summary}")
#         if feas.technical_risks:
#             for risk in feas.technical_risks:
#                 st.markdown(f"- **{risk.risk}** — Impact: {risk.impact}")

#     with tab_est:
#         est = st.session_state.estimation_output
#         _inc_mvp    = st.session_state.get("include_mvp", False)
#         _s_cols     = est.structural_columns or []
#         _tech_cols  = est.tech_stack_columns or []
#         df_est = _build_estimation_df(est.estimations, _s_cols, _tech_cols, include_mvp=_inc_mvp, totals=est.totals)
#         st.dataframe(df_est, use_container_width=True, hide_index=True,
#                      column_config=_estimation_col_config(_s_cols, _tech_cols, _inc_mvp))
#         totals = est.totals
#         st.markdown(f"**Grand Total: {totals.total_hours} hrs**")
#         if totals.tech_breakdown:
#             for tech, hrs in totals.tech_breakdown.items():
#                 st.markdown(f"- {tech}: **{hrs} hrs**")
#         if _inc_mvp and totals.phase1_hours is not None:
#             st.markdown(
#                 f"MVP: **{totals.phase1_hours} hrs** &nbsp;|&nbsp; Full Build: **{totals.phase2_hours} hrs**",
#                 unsafe_allow_html=True,
#             )

#     # Feedback + action buttons
#     st.markdown("---")

#     hitl2_feedback = st.text_area(
#         "💬 What would you like to change? (optional — describe what to adjust before regenerating)",
#         placeholder="e.g. 'Switch the backend to FastAPI instead of Django', 'The feasibility underestimates the AI pipeline risk', 'Add a mobile app phase to the estimation'",
#         height=80,
#         key="hitl2_feedback",
#     )

#     c1, c2, c3, c4 = st.columns(4)

#     with c1:
#         if st.button("✅ Approve Everything", type="primary", use_container_width=True, key="hitl2_approve_btn"):
#             st.session_state.approved_plan = st.session_state.plan_output.model_dump()
#             st.session_state.approved_feasibility = st.session_state.feasibility_output.model_dump()
#             st.session_state.approved_estimation = st.session_state.estimation_output.model_dump()
#             st.success("All outputs approved! Generating report...")
#             st.rerun()

#     with c2:
#         if st.button("🔄 Regenerate Plan", use_container_width=True, key="hitl2_regen_plan_btn"):
#             with st.spinner("🏗️ Regenerating plan..."):
#                 try:
#                     _pid = (st.session_state.selected_project or {}).get("id")
#                     result = call_planning_agent(st.session_state.approved_requirements, project_id=_pid, feedback=hitl2_feedback)
#                     st.session_state.plan_output = result
#                     st.session_state.feasibility_output = None
#                     st.session_state.estimation_output = None
#                     st.session_state.approved_plan = None
#                     st.session_state.approved_feasibility = None
#                     st.session_state.approved_estimation = None
#                     st.session_state.report_output = None
#                     st.rerun()
#                 except Exception as e:
#                     st.error(f"Plan regeneration failed: {e}")

#     with c3:
#         if st.button("🔁 Re-run Feasibility", use_container_width=True, key="hitl2_rerun_feas_btn"):
#             with st.spinner("🔍 Re-running feasibility..."):
#                 try:
#                     result = call_feasibility_agent(
#                         st.session_state.approved_requirements,
#                         st.session_state.plan_output.model_dump(),
#                         feedback=hitl2_feedback,
#                     )
#                     st.session_state.feasibility_output = result
#                     st.session_state.estimation_output = None
#                     st.session_state.approved_feasibility = None
#                     st.session_state.approved_estimation = None
#                     st.session_state.report_output = None
#                     st.rerun()
#                 except Exception as e:
#                     st.error(f"Feasibility re-run failed: {e}")

#     with c4:
#         if st.button("📊 Regenerate Estimation", use_container_width=True, key="hitl2_regen_est_btn"):
#             with st.spinner("📊 Regenerating estimation..."):
#                 try:
#                     _pid = (st.session_state.selected_project or {}).get("id")
#                     result = call_estimation_agent(
#                         st.session_state.approved_requirements,
#                         st.session_state.plan_output.model_dump(),
#                         st.session_state.feasibility_output.model_dump(),
#                         project_id=_pid,
#                         transcript=st.session_state.get("current_transcript", ""),
#                         include_mvp=st.session_state.get("include_mvp", False),
#                         feedback=hitl2_feedback,
#                     )
#                     st.session_state.estimation_output = result
#                     st.session_state.approved_estimation = None
#                     st.session_state.report_output = None
#                     st.rerun()
#                 except Exception as e:
#                     st.error(f"Estimation regeneration failed: {e}")

#     if st.session_state.approved_estimation:
#         st.success("🎉 All outputs are **approved**! Report generation is the next phase.")

#     st.markdown('<div style="height:0.5rem"></div>', unsafe_allow_html=True)


# # -------------------------------------------------------------
# # Report Agent Section
# # -------------------------------------------------------------
# def render_report_section():
#     st.markdown(
#         '<div class="accent-bar-purple"></div>'
#         + _step_header("7", "Final Report",
#             "12-section professional consulting report — suitable for client, business & technical review",
#             "violet"),
#         unsafe_allow_html=True,
#     )

#     if not st.session_state.report_output:
#         st.markdown(
#             "Generate a professional 12-section consulting report from all approved agent outputs. "
#             "The report is suitable for Client Review, Business Review, Technical Review, "
#             "Project Planning, and Effort Estimation Review."
#         )
#         if st.button("▶ Generate Final Report", type="primary", use_container_width=True, key="run_report_btn"):
#             approved_req = st.session_state.approved_requirements or {}
#             approved_plan = st.session_state.approved_plan or (st.session_state.plan_output.model_dump() if st.session_state.plan_output else {})
#             approved_feas = st.session_state.approved_feasibility or (st.session_state.feasibility_output.model_dump() if st.session_state.feasibility_output else {})
#             approved_est = st.session_state.approved_estimation or (st.session_state.estimation_output.model_dump() if st.session_state.estimation_output else {})

#             with st.spinner("Generating consulting report... this may take a minute."):
#                 try:
#                     result = call_report_agent(approved_req, approved_plan, approved_feas, approved_est)
#                     st.session_state.report_output = result.model_dump()
#                     st.success("✅ Final Report generated successfully!")
#                     st.rerun()
#                 except Exception as e:
#                     st.error(f"Report generation failed: {e}")
#     else:
#         report = st.session_state.report_output
#         raw = report.get("raw_data", {})
#         plan_data = raw.get("plan", {})
#         est_data = raw.get("estimation", {})
#         mermaid = plan_data.get("mermaid_diagram", "")

#         col_regen, _ = st.columns([1, 3])
#         with col_regen:
#             if st.button("🔄 Regenerate Report", key="regen_report_btn"):
#                 st.session_state.report_output = None
#                 st.rerun()

#         # ── Report cover header ───────────────────────────────────────────
#         from datetime import datetime as _dt
#         _proj_name = (st.session_state.selected_project or {}).get("name", "Project")
#         st.markdown(
#             f'<div style="background:linear-gradient(135deg,rgba(99,102,241,0.18) 0%,'
#             f'rgba(124,58,237,0.12) 100%);border:1px solid rgba(99,102,241,0.3);'
#             f'border-radius:14px;padding:1.75rem 2rem;margin-bottom:1.5rem">'
#             f'<div style="font-size:0.7rem;font-weight:700;text-transform:uppercase;'
#             f'letter-spacing:0.14em;color:#818CF8;margin-bottom:0.4rem">Consulting Report</div>'
#             f'<div style="font-size:1.6rem;font-weight:800;color:#E2E8F0;letter-spacing:-0.4px;'
#             f'line-height:1.2;margin-bottom:0.5rem">{_proj_name}</div>'
#             f'<div style="display:flex;gap:1.5rem;flex-wrap:wrap">'
#             f'<span style="font-size:0.78rem;color:#64748B">📅 {_dt.now().strftime("%B %d, %Y")}</span>'
#             f'<span style="font-size:0.78rem;color:#64748B">🤖 AI-Generated POC Analysis</span>'
#             f'<span style="font-size:0.78rem;color:#64748B">📋 11-Section Report</span>'
#             f'</div></div>',
#             unsafe_allow_html=True,
#         )

#         def _rpt_section(num: str, title: str, icon: str = "", color: str = "#6366F1") -> None:
#             st.markdown(
#                 f'<div style="display:flex;align-items:center;gap:0.75rem;'
#                 f'margin:1.5rem 0 0.75rem;padding-bottom:0.6rem;'
#                 f'border-bottom:2px solid {color}33">'
#                 f'<div style="min-width:28px;height:28px;border-radius:7px;'
#                 f'background:{color}22;border:1px solid {color}55;color:{color};'
#                 f'display:flex;align-items:center;justify-content:center;'
#                 f'font-size:0.78rem;font-weight:800;flex-shrink:0">{num}</div>'
#                 f'<div style="font-size:1.05rem;font-weight:700;color:#E2E8F0">'
#                 f'{icon} {title}</div></div>',
#                 unsafe_allow_html=True,
#             )

#         # ── 1. Executive Summary ──────────────────────────────────────────
#         _rpt_section("01", "Executive Summary", "📋", "#6366F1")
#         st.markdown(
#             f'<div style="background:rgba(99,102,241,0.07);border-left:3px solid #6366F1;'
#             f'border-radius:0 10px 10px 0;padding:1rem 1.25rem;margin-bottom:0.5rem;'
#             f'font-size:0.92rem;color:#CBD5E1;line-height:1.7">'
#             f'{report.get("executive_summary","").replace(chr(10),"<br>")}</div>',
#             unsafe_allow_html=True,
#         )

#         # ── 2. Background Summary ─────────────────────────────────────────
#         _rpt_section("02", "Background Summary", "🏢", "#7C3AED")
#         st.markdown(report.get("background_summary", ""))

#         # ── 3. Problem / Need Analysis ────────────────────────────────────
#         _rpt_section("03", "Problem / Need Analysis", "🎯", "#F43F5E")
#         pna = report.get("problem_need_analysis", [])
#         if pna:
#             df_pna = pd.DataFrame([
#                 {"Problem / Need": r.get("problem_need", ""), "Business Impact": r.get("business_impact", "")}
#                 for r in pna
#             ])
#             st.dataframe(df_pna, use_container_width=True, hide_index=True,
#                          column_config={
#                              "Problem / Need": st.column_config.TextColumn("Problem / Need", width="medium"),
#                              "Business Impact": st.column_config.TextColumn("Business Impact", width="large"),
#                          })
#         # ── 4. Requirements Analysis ──────────────────────────────────────
#         _rpt_section("04", "Requirements Analysis", "📝", "#0EA5E9")
#         tab_fr, tab_nfr, tab_con, tab_goals, tab_tech = st.tabs([
#             "Functional", "Non-Functional", "Constraints", "Business Goals", "Tech Context"
#         ])

#         with tab_fr:
#             fr = report.get("functional_requirements", [])
#             if fr:
#                 df_fr = pd.DataFrame([
#                     {"ID": r.get("id", ""), "Requirement": r.get("requirement", "")}
#                     for r in fr
#                 ])
#                 st.dataframe(df_fr, use_container_width=True, hide_index=True,
#                              column_config={
#                                  "ID": st.column_config.TextColumn("ID", width="small"),
#                                  "Requirement": st.column_config.TextColumn("Requirement", width="large"),
#                              })
#             else:
#                 st.info("No functional requirements.")

#         with tab_nfr:
#             nfr = report.get("non_functional_requirements", [])
#             if nfr:
#                 df_nfr = pd.DataFrame([
#                     {"Category": r.get("category", ""), "Requirement": r.get("requirement", "")}
#                     for r in nfr
#                 ])
#                 st.dataframe(df_nfr, use_container_width=True, hide_index=True,
#                              column_config={
#                                  "Category": st.column_config.TextColumn("Category", width="small"),
#                                  "Requirement": st.column_config.TextColumn("Requirement", width="large"),
#                              })
#             else:
#                 st.info("No non-functional requirements.")

#         with tab_con:
#             constraints = report.get("constraints", [])
#             if constraints:
#                 df_con = pd.DataFrame([{"Constraint": c} for c in constraints])
#                 st.dataframe(df_con, use_container_width=True, hide_index=True)
#             else:
#                 st.info("No constraints.")

#         with tab_goals:
#             goals = report.get("business_goals", [])
#             if goals:
#                 df_goals = pd.DataFrame([{"Goal": g} for g in goals])
#                 st.dataframe(df_goals, use_container_width=True, hide_index=True)
#             else:
#                 st.info("No business goals.")

#         with tab_tech:
#             tech_ctx = report.get("technology_context", [])
#             if tech_ctx:
#                 df_tech = pd.DataFrame([{"Technology Context": t} for t in tech_ctx])
#                 st.dataframe(df_tech, use_container_width=True, hide_index=True)
#             else:
#                 st.info("No technology context.")

#         # ── 5. Assumptions ────────────────────────────────────────────────
#         _rpt_section("05", "Assumptions", "💡", "#F59E0B")
#         assumptions = report.get("assumptions", [])
#         if assumptions:
#             df_ass = pd.DataFrame([{"Assumption": a} for a in assumptions])
#             st.dataframe(df_ass, use_container_width=True, hide_index=True)
#         # ── 6. Feature & Module Breakdown ─────────────────────────────────
#         _rpt_section("06", "Feature & Module Breakdown", "🧩", "#10B981")
#         fmb = report.get("feature_module_breakdown", [])
#         if fmb:
#             df_fmb = pd.DataFrame([
#                 {
#                     "Module": r.get("module", ""),
#                     "Feature / Functionality": r.get("feature_functionality", ""),
#                     "Technologies Used": r.get("technologies_used", ""),
#                 }
#                 for r in fmb
#             ])
#             st.dataframe(df_fmb, use_container_width=True, hide_index=True,
#                          column_config={
#                              "Module": st.column_config.TextColumn("Module", width="medium"),
#                              "Feature / Functionality": st.column_config.TextColumn("Feature / Functionality", width="large"),
#                              "Technologies Used": st.column_config.TextColumn("Technologies Used", width="medium"),
#                          })
#         # ── 7. Final Solution Architecture ────────────────────────────────
#         _rpt_section("07", "Solution Architecture", "🗺️", "#6366F1")
#         if mermaid:
#             with st.expander("📊 View Architecture Diagram", expanded=True):
#                 render_mermaid_diagram(mermaid)
#             with st.expander("📝 Diagram Source (Mermaid)", expanded=False):
#                 st.code(mermaid, language="mermaid")
#         else:
#             st.info("Architecture diagram not available.")
#         # ── 8. Feasibility Assessment ─────────────────────────────────────
#         _rpt_section("08", "Feasibility Assessment", "🔍", "#8B5CF6")
#         ft = report.get("feasibility_table", [])
#         if ft:
#             df_ft = pd.DataFrame([
#                 {"Metric": r.get("metric", ""), "Value": r.get("value", ""), "Reason": r.get("reason", "")}
#                 for r in ft
#             ])
#             st.dataframe(df_ft, use_container_width=True, hide_index=True,
#                          column_config={
#                              "Metric": st.column_config.TextColumn("Metric", width="small"),
#                              "Value": st.column_config.TextColumn("Value", width="small"),
#                              "Reason": st.column_config.TextColumn("Reason", width="large"),
#                          })
#         # ── 9. Risk Assessment ────────────────────────────────────────────
#         _rpt_section("09", "Risk Assessment", "⚠️", "#F43F5E")
#         ra = report.get("risk_assessment", [])
#         if ra:
#             df_ra = pd.DataFrame([
#                 {
#                     "Risk": r.get("risk", ""),
#                     "Impact": r.get("impact", ""),
#                     "Mitigation Strategy": r.get("mitigation_strategy", ""),
#                 }
#                 for r in ra
#             ])
#             st.dataframe(df_ra, use_container_width=True, hide_index=True,
#                          column_config={
#                              "Risk": st.column_config.TextColumn("Risk", width="medium"),
#                              "Impact": st.column_config.TextColumn("Impact", width="small"),
#                              "Mitigation Strategy": st.column_config.TextColumn("Mitigation Strategy", width="large"),
#                          })
#         # ── 10. Recommendations & Next Steps ──────────────────────────────
#         _rpt_section("10", "Recommendations & Next Steps", "🚀", "#10B981")
#         st.markdown(report.get("recommendations_next_steps", ""))

#         # ── 11. Architecture Summary ───────────────────────────────────────
#         _rpt_section("11", "Architecture Summary", "📐", "#0EA5E9")
#         st.markdown(report.get("architecture_summary", ""))

#         # ── Effort Estimation Details ─────────────────────────────────────
#         if est_data:
#             with st.expander("📊 Effort Estimation Details", expanded=False):
#                 estimations  = est_data.get("estimations", [])
#                 totals       = est_data.get("totals", {})
#                 _s_cols_r    = est_data.get("structural_columns", [])
#                 _tech_cols_r = est_data.get("tech_stack_columns", [])
#                 _inc_mvp_r   = st.session_state.get("include_mvp", False)

#                 if estimations:
#                     df = _build_estimation_df(estimations, _s_cols_r, _tech_cols_r, include_mvp=_inc_mvp_r, totals=totals)
#                     st.dataframe(df, use_container_width=True, hide_index=True,
#                                  column_config=_estimation_col_config(_s_cols_r, _tech_cols_r, _inc_mvp_r))
#                     st.markdown(f"**Grand Total: {totals.get('total_hours', 0)} hrs**")
#                     tech_breakdown = totals.get("tech_breakdown", {})
#                     if tech_breakdown:
#                         for tech, hrs in tech_breakdown.items():
#                             st.markdown(f"- {tech}: **{hrs} hrs**")

#                     est_buffer = io.BytesIO()
#                     with pd.ExcelWriter(est_buffer, engine="openpyxl") as writer:
#                         df.to_excel(writer, index=False, sheet_name="Effort Estimation")
#                     est_buffer.seek(0)
#                     st.download_button(
#                         label="📥 Download Estimation as Excel",
#                         data=est_buffer,
#                         file_name="effort_estimation.xlsx",
#                         mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
#                         use_container_width=True,
#                         key="dl_report_est_excel",
#                     )

#         # ── Downloads ─────────────────────────────────────────────────────
#         st.markdown("#### 📥 Download Report")
#         d1, d2, d3, d4 = st.columns(4)

#         with d1:
#             docx_buf = generate_docx(report)
#             st.download_button(
#                 label="📄 Word (.docx)",
#                 data=docx_buf,
#                 file_name="project_report.docx",
#                 mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
#                 use_container_width=True,
#                 key="dl_report_docx",
#             )

#         with d2:
#             pdf_buf = generate_pdf(report)
#             st.download_button(
#                 label="📑 PDF (.pdf)",
#                 data=pdf_buf,
#                 file_name="project_report.pdf",
#                 mime="application/pdf",
#                 use_container_width=True,
#                 key="dl_report_pdf",
#             )

#         with d3:
#             json_buf = generate_json(report)
#             st.download_button(
#                 label="📋 JSON (.json)",
#                 data=json_buf,
#                 file_name="project_report.json",
#                 mime="application/json",
#                 use_container_width=True,
#                 key="dl_report_json",
#             )

#         with d4:
#             md_buf = generate_markdown(report)
#             st.download_button(
#                 label="📝 Markdown (.md)",
#                 data=md_buf,
#                 file_name="project_report.md",
#                 mime="text/markdown",
#                 use_container_width=True,
#                 key="dl_report_md",
#             )

#     st.markdown('<div style="height:0.5rem"></div>', unsafe_allow_html=True)


# # -------------------------------------------------------------
# # Main Application Dashboard
# # -------------------------------------------------------------
# def render_dashboard():
#     user = st.session_state.user
 
#     # --- Sidebar ---
#     st.sidebar.markdown(
#         '<div style="font-size:0.68rem;font-weight:700;text-transform:uppercase;'
#         'letter-spacing:0.1em;color:#334155;padding-bottom:0.4rem">Signed In As</div>',
#         unsafe_allow_html=True,
#     )
#     st.sidebar.markdown(
#         f'<div style="font-size:0.85rem;color:#94A3B8;font-weight:500;'
#         f'padding:0.5rem 0.75rem;background:rgba(255,255,255,0.04);border-radius:7px;'
#         f'border:1px solid rgba(255,255,255,0.07);margin-bottom:0.5rem;word-break:break-all">'
#         f'{user.email}</div>',
#         unsafe_allow_html=True,
#     )
 
#     if st.sidebar.button("Sign Out", use_container_width=True, key="signout_btn"):
#         try:
#             db.sign_out()
#         except Exception:
#             pass
#         st.session_state.user = None
#         st.session_state.selected_project = None
#         st.session_state.task_output = None
#         st.session_state.approved_requirements = None
#         st.session_state["_transcript_exists"] = False
#         reset_planning_pipeline()
#         st.rerun()

#     st.sidebar.markdown(
#         '<div style="height:1px;background:rgba(255,255,255,0.06);margin:0.75rem 0"></div>'
#         '<div style="font-size:0.68rem;font-weight:700;text-transform:uppercase;'
#         'letter-spacing:0.1em;color:#334155;padding-bottom:0.5rem">Projects</div>',
#         unsafe_allow_html=True,
#     )
 
#     try:
#         projects = _cached_get_projects(user.id)
#     except Exception as e:
#         st.sidebar.error(f"Failed to fetch projects: {e}")
#         projects = []
 
#     project_options = ["-- Select a Project --"] + [p["name"] for p in projects]
 
#     selected_index = 0
#     if st.session_state.selected_project:
#         for idx, p in enumerate(projects):
#             if p["id"] == st.session_state.selected_project["id"]:
#                 selected_index = idx + 1
#                 break
 
#     # Store for on_change callback (callbacks cannot read local variables)
#     st.session_state["_projects_list"] = projects

#     def _on_project_change():
#         chosen = st.session_state["project_selector"]
#         _projects = st.session_state.get("_projects_list", [])
#         if chosen == "-- Select a Project --":
#             st.session_state.selected_project = None
#             st.session_state.task_output = None
#             st.session_state.approved_requirements = None
#             reset_planning_pipeline()
#         else:
#             sel = next((p for p in _projects if p["name"] == chosen), None)
#             if sel is None:
#                 st.session_state.selected_project = None
#             elif (
#                 not st.session_state.selected_project
#                 or st.session_state.selected_project["id"] != sel["id"]
#             ):
#                 st.session_state.selected_project = sel
#                 st.session_state.task_output = None
#                 st.session_state.approved_requirements = None
#                 st.session_state["_transcript_exists"] = False
#                 reset_planning_pipeline()

#     st.sidebar.selectbox(
#         "Select Active Project",
#         options=project_options,
#         index=selected_index,
#         key="project_selector",
#         on_change=_on_project_change,
#     )
 
#     st.sidebar.markdown(
#         '<div style="font-size:0.72rem;font-weight:600;color:#475569;margin-top:0.75rem;margin-bottom:0.25rem">'
#         'Create New Project</div>',
#         unsafe_allow_html=True,
#     )
#     new_proj_name = st.sidebar.text_input("Project Name", placeholder="e.g. Client X - Core POC", key="new_proj_input")
#     if st.sidebar.button("Add Project", type="primary", use_container_width=True, key="add_proj_btn"):
#         if not new_proj_name.strip():
#             st.sidebar.warning("Please enter a project name.")
#         else:
#             try:
#                 new_project = db.create_project(user.id, new_proj_name.strip())
#                 _cached_get_projects.clear()
#                 st.session_state.selected_project = new_project
#                 st.session_state.task_output = None
#                 st.session_state.approved_requirements = None
#                 reset_planning_pipeline()
#                 st.sidebar.success(f"Project '{new_proj_name}' created!")
#                 st.rerun()
#             except Exception as e:
#                 st.sidebar.error(f"Failed to create project: {e}")
 
#     # --- Reference Document Upload (RAG) ---
#     st.sidebar.markdown(
#         '<div style="height:1px;background:rgba(255,255,255,0.06);margin:0.75rem 0"></div>'
#         '<div style="font-size:0.68rem;font-weight:700;text-transform:uppercase;'
#         'letter-spacing:0.1em;color:#334155;padding-bottom:0.25rem">Reference Documents</div>'
#         '<div style="font-size:0.75rem;color:#334155;margin-bottom:0.5rem">'
#         'Upload SOW, BRD, specs or prior estimates to enrich AI context</div>',
#         unsafe_allow_html=True,
#     )

#     if st.session_state.selected_project:
#         _rag_pid = st.session_state.selected_project["id"]

#         uploaded_ref_files = st.sidebar.file_uploader(
#             "Upload reference docs",
#             type=["pdf", "docx", "txt"],
#             accept_multiple_files=True,
#             key="ref_doc_uploader",
#             label_visibility="collapsed",
#         )

#         if uploaded_ref_files:
#             if st.sidebar.button("📤 Ingest Documents", use_container_width=True, key="ingest_docs_btn"):
#                 for _uf in uploaded_ref_files:
#                     _ext = _uf.name.rsplit(".", 1)[-1].lower()
#                     with st.sidebar:
#                         with st.spinner(f"Ingesting {_uf.name}…"):
#                             _res = ingest_document(_rag_pid, _uf.read(), _uf.name, _ext)
#                     if _res["success"]:
#                         _cached_list_documents.clear()
#                         st.sidebar.success(f"✅ {_uf.name}: {_res['chunks_inserted']} chunks")
#                     else:
#                         st.sidebar.error(f"❌ {_uf.name}: {_res.get('error', 'Failed')}")

#         try:
#             _existing_docs = _cached_list_documents(_rag_pid)
#             if _existing_docs:
#                 st.sidebar.markdown("**Indexed docs:**")
#                 for _rdoc in _existing_docs:
#                     _rc1, _rc2 = st.sidebar.columns([5, 1])
#                     _rc1.caption(f"📄 {_rdoc['document_name'][:28]}")
#                     if _rc2.button("✕", key=f"del_rdoc_{_rag_pid}_{_rdoc['document_name']}"):
#                         delete_project_documents(_rag_pid, _rdoc["document_name"])
#                         _cached_list_documents.clear()
#                         st.rerun()
#             else:
#                 st.sidebar.caption("No documents indexed yet.")
#         except Exception:
#             st.sidebar.caption("Could not load document list.")
#     else:
#         st.sidebar.caption("Select a project to upload documents.")

#     # --- Pipeline status in sidebar ---
#     transcript_done = bool(st.session_state.get("_transcript_exists", False))
#     task_done = bool(st.session_state.task_output)
#     approved_done = bool(st.session_state.approved_requirements)
#     plan_done = bool(st.session_state.plan_output)
#     feasibility_done = bool(st.session_state.feasibility_output)
#     feasibility_approved_done = bool(st.session_state.get("approved_feasibility"))
#     estimation_done = bool(st.session_state.estimation_output)
#     estimation_approved_done = bool(st.session_state.approved_estimation)
#     report_done = bool(st.session_state.report_output)

#     pipeline_steps = [
#         ("Transcript Upload",       transcript_done),
#         ("Task Agent",              task_done),
#         ("HITL #1 — Requirements",  approved_done),
#         ("Planning Agent",          plan_done),
#         ("Feasibility Agent",       feasibility_done),
#         ("HITL #2 — Plan & Feas.",  feasibility_approved_done),
#         ("Estimation Agent",        estimation_done),
#         ("HITL #3 — Estimation",    estimation_approved_done),
#         ("Final Report",            report_done),
#     ]
#     completed = sum(1 for _, d in pipeline_steps if d)
#     total = len(pipeline_steps)

#     st.sidebar.markdown(
#         '<div style="height:1px;background:rgba(255,255,255,0.06);margin:0.75rem 0"></div>'
#         f'<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:0.6rem">'
#         f'<div style="font-size:0.68rem;font-weight:700;text-transform:uppercase;'
#         f'letter-spacing:0.1em;color:#334155">Pipeline Progress</div>'
#         f'<div style="font-size:0.75rem;font-weight:600;color:#{"34D399" if completed==total else "6366F1"}">'
#         f'{completed}/{total}</div></div>',
#         unsafe_allow_html=True,
#     )
#     st.sidebar.markdown(_pipeline_html(pipeline_steps), unsafe_allow_html=True)

#     # Apply theme (JS sets data-theme attr on <html>)
#     _apply_theme(st.session_state.get("app_theme", "dark"))

#     # --- Main Content ---
#     # Theme toggle + page title row
#     _hdr_left, _hdr_right = st.columns([5, 1])
#     with _hdr_left:
#         st.markdown(
#             '<div class="main-title"><span style="color:#6366F1">⚡</span> AI-Powered POC Generator</div>',
#             unsafe_allow_html=True,
#         )
#         st.markdown(
#             '<div class="subtitle">Transform client conversations into production-ready project plans &amp; estimates.</div>',
#             unsafe_allow_html=True,
#         )
#     with _hdr_right:
#         _ct = st.session_state.get("app_theme", "dark")
#         _cycle  = {"dark": "light", "light": "system", "system": "dark"}
#         _icons  = {"dark": "🌙", "light": "☀️", "system": "💻"}
#         _labels = {"dark": "Dark — click for Light", "light": "Light — click for System", "system": "System — click for Dark"}
#         st.markdown('<div style="padding-top:0.4rem"></div>', unsafe_allow_html=True)
#         if st.button(_icons[_ct], key="th_toggle", help=_labels[_ct], use_container_width=True):
#             st.session_state.app_theme = _cycle[_ct]
#             st.rerun()

#     if not st.session_state.selected_project:
#         st.markdown('<div class="accent-bar"></div>', unsafe_allow_html=True)
#         st.info("👈 Select an existing project or create a new one from the sidebar to get started.")
#         return

#     project = st.session_state.selected_project
#     st.markdown(
#         f'<div style="font-size:0.8rem;font-weight:600;color:#475569;text-transform:uppercase;'
#         f'letter-spacing:0.09em;margin-bottom:0.3rem">Active Project</div>'
#         f'<div style="font-size:1.2rem;font-weight:700;color:#E2E8F0;margin-bottom:1.5rem">'
#         f'{project["name"]}</div>',
#         unsafe_allow_html=True,
#     )

#     # ── Step 1: Transcript Upload ──────────────────────────────
#     col_left, col_right = st.columns([1.2, 0.8])
 
#     existing_transcript = ""
#     try:
#         transcript_record = _cached_get_transcript(project["id"])
#         if transcript_record:
#             existing_transcript = transcript_record.get("content", "")
#         st.session_state["_transcript_exists"] = bool(existing_transcript.strip())
#         st.session_state["current_transcript"] = existing_transcript
#     except Exception as e:
#         st.error(f"Error fetching transcript: {e}")
#         st.session_state["_transcript_exists"] = False
#         st.session_state["current_transcript"] = ""
 
#     with col_left:
#         st.markdown(
#             '<div class="accent-bar-purple"></div>'
#             + _step_header("1", "Upload Client Meeting Transcript",
#                 "Upload a PDF / DOCX / TXT file or paste transcript text directly",
#                 "violet"),
#             unsafe_allow_html=True,
#         )
 
#         uploaded_file = st.file_uploader(
#             "Upload Meeting Transcript (PDF, DOCX, or TXT)",
#             type=["txt", "pdf", "docx"],
#             key="transcript_uploader"
#         )
 
#         pasted_text = st.text_area(
#             "Or Paste Transcript here",
#             value=existing_transcript if not uploaded_file else "",
#             height=250,
#             placeholder="Client: We need a system that registers users via email...\nPartner: Understood...",
#             key="transcript_paste"
#         )
 
#         transcript_content = ""
#         if uploaded_file is not None:
#             try:
#                 file_bytes = uploaded_file.read()
#                 file_ext = uploaded_file.name.rsplit(".", 1)[-1].lower() if "." in uploaded_file.name else "txt"
#                 # Use extract_text to handle PDF, DOCX, and TXT formats
#                 transcript_content = extract_text(file_bytes, file_ext)
#                 st.info(f"📎 File '{uploaded_file.name}' loaded ({len(transcript_content)} characters extracted).")
#             except Exception as e:
#                 st.error(f"Failed to read file: {e}")
#         else:
#             transcript_content = pasted_text
 
#         if st.button("💾 Save & Upload Transcript", type="primary", key="save_transcript_btn"):
#             if not transcript_content.strip():
#                 st.warning("Please upload a file or paste transcript text before saving.")
#             else:
#                 try:
#                     db.upload_transcript(project["id"], transcript_content.strip())
#                     _cached_get_transcript.clear()
#                     st.success("🎉 Transcript saved to Supabase!")
#                     st.rerun()
#                 except Exception as e:
#                     st.error(f"Failed to upload transcript: {e}")

#     with col_right:
#         st.markdown(
#             '<div class="accent-bar"></div>'
#             '<div style="font-size:0.78rem;font-weight:700;text-transform:uppercase;'
#             'letter-spacing:0.09em;color:#475569;margin-bottom:0.75rem">Transcript Preview</div>',
#             unsafe_allow_html=True,
#         )
 
#         if existing_transcript.strip():
#             st.markdown("<span class='status-badge status-completed'>✅ SAVED</span>", unsafe_allow_html=True)
#             st.markdown("---")
#             preview = existing_transcript[:600] + ("..." if len(existing_transcript) > 600 else "")
#             st.text(preview)
#         else:
#             st.markdown("<span class='status-badge status-pending'>NOT UPLOADED</span>", unsafe_allow_html=True)
#             st.info("No transcript saved yet for this project.")

#     st.markdown('<div style="height:0.5rem"></div>', unsafe_allow_html=True)

#     # ── Step 2: Task Agent + HITL ──────────────────────────────
#     if existing_transcript.strip():
#         render_task_agent_section(existing_transcript, project["id"])
#     else:
#         st.markdown("---")
#         st.info("📌 Upload and save a transcript above to enable the Task Agent.")

#     # ── Steps 3+4: Planning + Feasibility ─────────────────────
#     # When both have been auto-run via HITL #1, show as compact expanders so
#     # HITL #2 appears immediately below without requiring extra clicks.
#     if st.session_state.approved_requirements:
#         if st.session_state.plan_output and st.session_state.feasibility_output:
#             with st.expander("🏗️ Planning Agent Results — click to view or re-run", expanded=False):
#                 render_planning_agent_section()
#             with st.expander("🔍 Feasibility Agent Results — click to view or re-run", expanded=False):
#                 render_feasibility_section()
#         elif st.session_state.plan_output:
#             render_planning_agent_section()
#             render_feasibility_section()
#         else:
#             render_planning_agent_section()
#     elif existing_transcript.strip() and st.session_state.task_output:
#         st.markdown("---")
#         st.info("📌 Approve the extracted requirements above to enable the Planning Agent.")

#     # ── Step 4b: HITL #2 — Approve Plan + Feasibility ─────────
#     if st.session_state.plan_output and st.session_state.feasibility_output:
#         st.markdown(
#             '<div class="accent-bar-green"></div>'
#             + _step_header("4b", "HITL #2 — Review Plan & Feasibility",
#                 "Approve or refine planning and feasibility outputs before running the Estimation Agent",
#                 "amber"),
#             unsafe_allow_html=True,
#         )

#         hitl2b_feedback = st.text_area(
#             "💬 What would you like to change? (optional — describe what to adjust before regenerating)",
#             placeholder="e.g. 'Use a microservices architecture instead of monolith', 'The feasibility missed the payment gateway risk'",
#             height=80,
#             key="hitl2b_feedback",
#         )

#         hitl2_col1, hitl2_col2, hitl2_col3, _ = st.columns([1, 1, 1, 1])

#         with hitl2_col1:
#             if st.button("✅ Approve Plan & Feasibility", type="primary", use_container_width=True, key="hitl2_approve_plan_feas_btn"):
#                 st.session_state.approved_plan = st.session_state.plan_output.model_dump()
#                 st.session_state.approved_feasibility = st.session_state.feasibility_output.model_dump()
#                 st.success("Plan and Feasibility approved! Ready for Estimation Agent.")
#                 st.rerun()

#         with hitl2_col2:
#             if st.button("🔄 Regenerate Plan", use_container_width=True, key="hitl2_regen_plan_btn"):
#                 with st.spinner("🏗️ Regenerating plan..."):
#                     try:
#                         _pid = (st.session_state.selected_project or {}).get("id")
#                         result = call_planning_agent(st.session_state.approved_requirements, project_id=_pid, feedback=hitl2b_feedback)
#                         st.session_state.plan_output = result
#                         st.session_state.feasibility_output = None
#                         st.session_state.approved_plan = None
#                         st.session_state.approved_feasibility = None
#                         st.session_state.estimation_output = None
#                         st.session_state.approved_estimation = None
#                         st.session_state.report_output = None
#                         st.rerun()
#                     except Exception as e:
#                         st.error(f"Plan regeneration failed: {e}")

#         with hitl2_col3:
#             if st.button("🔁 Re-run Feasibility", use_container_width=True, key="hitl2_reerun_feas_btn"):
#                 with st.spinner("🔍 Re-running feasibility..."):
#                     try:
#                         result = call_feasibility_agent(
#                             st.session_state.approved_requirements,
#                             st.session_state.plan_output.model_dump(),
#                             feedback=hitl2b_feedback,
#                         )
#                         st.session_state.feasibility_output = result
#                         st.session_state.approved_plan = None
#                         st.session_state.approved_feasibility = None
#                         st.session_state.estimation_output = None
#                         st.session_state.approved_estimation = None
#                         st.session_state.report_output = None
#                         st.rerun()
#                     except Exception as e:
#                         st.error(f"Feasibility re-run failed: {e}")

#         if st.session_state.get("approved_feasibility"):
#             st.success("🎉 Plan and Feasibility are **approved**! Ready for the Estimation Agent.")

#         st.markdown('<div style="height:0.5rem"></div>', unsafe_allow_html=True)
#     elif st.session_state.plan_output:
#         st.markdown("---")
#         st.info("📌 Run the Feasibility Agent above to enable HITL #2 review.")

#     # ── Step 5: Estimation Agent ────────────────────────────
#     if st.session_state.get("approved_feasibility"):
#         render_estimation_section()
#     elif st.session_state.plan_output and st.session_state.feasibility_output:
#         st.markdown("---")
#         st.info("📌 Approve Plan & Feasibility above to enable the Estimation Agent.")

#     # ── Step 6: HITL #3 — Approve Estimation ─────────────────
#     if st.session_state.estimation_output:
#         st.markdown(
#             '<div class="accent-bar-green"></div>'
#             + _step_header("6", "HITL #3 — Review Estimation",
#                 "Approve or refine the effort estimation before generating the final report",
#                 "amber"),
#             unsafe_allow_html=True,
#         )

#         hitl3_feedback = st.text_area(
#             "💬 What would you like to change? (optional — describe what to adjust before regenerating)",
#             placeholder="e.g. 'Phase 1 is too heavy, move notifications to Phase 2', 'Add a dedicated DevOps module', 'The QA effort seems underestimated'",
#             height=80,
#             key="hitl3_est_feedback",
#         )

#         hitl3_col1, hitl3_col2, _ = st.columns([1, 1, 2])

#         with hitl3_col1:
#             if st.button("✅ Approve Estimation", type="primary", use_container_width=True, key="hitl3_approve_est_btn"):
#                 st.session_state.approved_estimation = st.session_state.estimation_output.model_dump()
#                 st.success("Estimation approved! Ready for Report Agent.")
#                 st.rerun()

#         with hitl3_col2:
#             if st.button("📊 Regenerate Estimation", use_container_width=True, key="hitl3_regen_est_btn"):
#                 with st.spinner("📊 Regenerating estimation..."):
#                     try:
#                         _pid = (st.session_state.selected_project or {}).get("id")
#                         result = call_estimation_agent(
#                             st.session_state.approved_requirements,
#                             st.session_state.plan_output.model_dump(),
#                             st.session_state.feasibility_output.model_dump(),
#                             project_id=_pid,
#                             transcript=st.session_state.get("current_transcript", ""),
#                             include_mvp=st.session_state.get("include_mvp", False),
#                             feedback=hitl3_feedback,
#                         )
#                         st.session_state.estimation_output = result
#                         st.session_state.approved_estimation = None
#                         st.session_state.report_output = None
#                         st.rerun()
#                     except Exception as e:
#                         st.error(f"Estimation regeneration failed: {e}")

#         if st.session_state.approved_estimation:
#             st.success("🎉 Estimation is **approved**! Ready for the Report Agent.")

#         st.markdown('<div style="height:0.5rem"></div>', unsafe_allow_html=True)

#     # ── Step 7: Report Agent ──────────────────────────────────
#     if st.session_state.approved_estimation:
#         render_report_section()

# # -------------------------------------------------------------
# # Page router
# # -------------------------------------------------------------
# if st.session_state.user is None:
#     render_auth_page()
# else:
#     render_dashboard()
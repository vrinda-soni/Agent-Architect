import sys
from pathlib import Path

# Add root folder to sys.path if not present to ensure backend imports work
root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.append(str(root_dir))

import html
import io
import json
import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import backend.supabase as db
from backend.api.client import (
    call_task_agent,
    call_planning_agent,
    call_feasibility_agent,
    call_estimation_agent,
    call_report_agent,
)
from backend.report_generator import generate_docx, generate_pdf, generate_json, generate_markdown
from backend.rag.ingestion import ingest_document, delete_project_documents, list_project_documents, extract_text


# ── Cached DB helpers (avoid repeated Supabase round-trips per render) ────────

@st.cache_data(ttl=30, show_spinner=False)
def _cached_get_projects(user_id: str):
    return db.get_projects(user_id)

@st.cache_data(ttl=15, show_spinner=False)
def _cached_get_transcript(project_id: str):
    return db.get_transcript(project_id)

@st.cache_data(ttl=30, show_spinner=False)
def _cached_list_documents(project_id: str):
    return list_project_documents(project_id)


COMPLEXITY_BADGES = {
    "low": ("🟢", "Low"),
    "medium": ("🟡", "Medium"),
    "high": ("🟠", "High"),
    "very high": ("🔴", "Very High"),
}

CONFIDENCE_BADGES = {
    "high": ("🟢", "High"),
    "medium": ("🟡", "Medium"),
    "low": ("🔴", "Low"),
}


def level_badge_html(level: str, badge_map: dict) -> str:
    key = (level or "").strip().lower()
    emoji, label = badge_map.get(key, ("⚪", level or "Unknown"))
    return f'<div class="level-badge">{emoji} {label}</div>'


def _sanitize_mermaid(diagram: str) -> str:
    """Robustly clean LLM-generated mermaid diagrams for mermaid.js v10."""
    import re
    cleaned = diagram.strip()
    # Strip markdown code fence
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`").strip()
        if cleaned.startswith("mermaid"):
            cleaned = cleaned[7:].strip()
    # Replace semicolons with newlines (LLM often uses semicolons as separators)
    cleaned = cleaned.replace(";", "\n")
    # Normalise escaped newlines (\n literal in JSON strings)
    cleaned = cleaned.replace("\\n", "\n")
    # Remove special characters that break mermaid syntax
    cleaned = re.sub(r'[^\x20-\x7E\n\t]', '', cleaned)  # Keep only printable ASCII
    # Remove problematic characters that cause syntax errors
    cleaned = cleaned.replace('"', "'")  # Replace double quotes with single
    cleaned = re.sub(r'[{}\[\]]', '', cleaned)  # Remove braces that can cause issues
    # Fix common LLM mistakes
    cleaned = re.sub(r'-->', '-->', cleaned)  # Normalize arrows
    cleaned = re.sub(r'--+>', '-->', cleaned)  # Fix multiple dashes
    cleaned = re.sub(r'-{3,}', '--', cleaned)  # Limit consecutive dashes
    # Remove empty lines and collapse multiple blank lines
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    # Ensure diagram starts with a valid declaration
    first_line = cleaned.split("\n")[0].strip().lower()
    valid_starts = ("flowchart", "graph ", "sequencediagram", "classdiagram",
                    "statediagram", "erdiagram", "gantt", "pie", "mindmap")
    if not any(first_line.startswith(v.lower()) for v in valid_starts):
        cleaned = "flowchart TD\n" + cleaned
    # Remove any trailing whitespace on each line
    lines = [line.rstrip() for line in cleaned.split("\n")]
    cleaned = "\n".join(lines)
    return cleaned.strip()


def render_mermaid_diagram(diagram: str, height: int = 540) -> None:
    cleaned = _sanitize_mermaid(diagram)
    safe_diagram = html.escape(cleaned)
    components.html(
        f"""<!DOCTYPE html>
<html>
<head>
    <script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
    <style>
        body {{
            margin: 0;
            padding: 16px;
            background: #0e1117;
            font-family: 'Segoe UI', sans-serif;
        }}
        .mermaid {{
            display: flex;
            justify-content: center;
        }}
        .mermaid svg {{
            max-width: 100%;
            height: auto;
        }}
    </style>
</head>
<body>
    <pre class="mermaid">{safe_diagram}</pre>
    <script>
        mermaid.initialize({{
            startOnLoad: true,
            theme: "dark",
            flowchart: {{ curve: "basis", padding: 20, useMaxWidth: true }},
            themeVariables: {{
                primaryColor: "#6622FF",
                primaryTextColor: "#ffffff",
                primaryBorderColor: "#FF3366",
                lineColor: "#888899",
                secondaryColor: "#FF9933",
                tertiaryColor: "#00d4aa",
                fontFamily: "'Segoe UI', sans-serif",
                fontSize: "15px"
            }}
        }});
    </script>
</body>
</html>""",
        height=height,
        scrolling=True,
    )
 
# -------------------------------------------------------------
# Premium Aesthetics & CSS Styling
# -------------------------------------------------------------
st.set_page_config(
    page_title="AI-Powered POC Generator",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded"
)
 
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700;800&display=swap');
 
    * { font-family: 'Outfit', sans-serif; }
 
    .main-title {
        font-size: 3rem;
        font-weight: 800;
        background: linear-gradient(135deg, #FF3366, #FF9933, #6622FF);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin-bottom: 0.5rem;
    }
 
    .subtitle {
        color: #888899;
        font-size: 1.2rem;
        font-weight: 400;
        margin-bottom: 2rem;
    }
 
    .glass-card {
        background: rgba(255, 255, 255, 0.03);
        border: 1px solid rgba(255, 255, 255, 0.05);
        border-radius: 16px;
        padding: 2rem;
        backdrop-filter: blur(10px);
        margin-bottom: 1.5rem;
    }
 
    .accent-bar {
        height: 4px;
        background: linear-gradient(90deg, #FF3366, #FF9933);
        border-radius: 2px;
        margin-bottom: 1.5rem;
    }
 
    .accent-bar-purple {
        height: 4px;
        background: linear-gradient(90deg, #6622FF, #00CCFF);
        border-radius: 2px;
        margin-bottom: 1.5rem;
    }
 
    .accent-bar-green {
        height: 4px;
        background: linear-gradient(90deg, #00C853, #00E5FF);
        border-radius: 2px;
        margin-bottom: 1.5rem;
    }
 
    .status-badge {
        display: inline-block;
        padding: 0.35rem 0.75rem;
        border-radius: 20px;
        font-size: 0.85rem;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.05em;
    }
 
    .status-active {
        background-color: rgba(0, 204, 255, 0.15);
        color: #00CCFF;
        border: 1px solid rgba(0, 204, 255, 0.3);
    }
 
    .status-completed {
        background-color: rgba(50, 205, 50, 0.15);
        color: #32CD32;
        border: 1px solid rgba(50, 205, 50, 0.3);
    }
 
    .status-pending {
        background-color: rgba(255, 165, 0, 0.15);
        color: #FFA500;
        border: 1px solid rgba(255, 165, 0, 0.3);
    }
 
    .requirement-item {
        background: rgba(102, 34, 255, 0.08);
        border-left: 3px solid #6622FF;
        padding: 0.6rem 1rem;
        border-radius: 0 8px 8px 0;
        margin-bottom: 0.5rem;
        font-size: 0.95rem;
    }
 
    .pain-item {
        background: rgba(255, 51, 102, 0.08);
        border-left: 3px solid #FF3366;
        padding: 0.6rem 1rem;
        border-radius: 0 8px 8px 0;
        margin-bottom: 0.5rem;
        font-size: 0.95rem;
    }
 
    .goal-item {
        background: rgba(0, 200, 83, 0.08);
        border-left: 3px solid #00C853;
        padding: 0.6rem 1rem;
        border-radius: 0 8px 8px 0;
        margin-bottom: 0.5rem;
        font-size: 0.95rem;
    }
 
    .constraint-item {
        background: rgba(255, 165, 0, 0.08);
        border-left: 3px solid #FFA500;
        padding: 0.6rem 1rem;
        border-radius: 0 8px 8px 0;
        margin-bottom: 0.5rem;
        font-size: 0.95rem;
    }
 
    div[data-baseweb="input"] { border-radius: 8px !important; }
 
    button[kind="primary"] {
        background: linear-gradient(135deg, #6622FF, #00CCFF) !important;
        border: none !important;
        color: white !important;
        font-weight: 600 !important;
        border-radius: 8px !important;
        padding: 0.5rem 2rem !important;
        transition: transform 0.2s ease, box-shadow 0.2s ease !important;
    }
 
    button[kind="primary"]:hover {
        transform: translateY(-2px);
        box-shadow: 0 4px 15px rgba(102, 34, 255, 0.4);
    }

    .metric-label {
        font-size: 0.8rem;
        color: #888899;
        text-transform: uppercase;
        letter-spacing: 0.06em;
        font-weight: 600;
        margin-bottom: 0.35rem;
    }

    .level-badge {
        display: inline-block;
        padding: 0.45rem 0.9rem;
        border-radius: 12px;
        font-size: 1.05rem;
        font-weight: 600;
        background: rgba(255, 255, 255, 0.05);
        border: 1px solid rgba(255, 255, 255, 0.1);
    }

    .metric-card {
        background: rgba(255, 255, 255, 0.03);
        border: 1px solid rgba(255, 255, 255, 0.06);
        border-radius: 12px;
        padding: 1rem 1.25rem;
        margin-bottom: 0.5rem;
    }
</style>
""", unsafe_allow_html=True)
 
# -------------------------------------------------------------
# Session State Initialization
# -------------------------------------------------------------
if "user" not in st.session_state:
    st.session_state.user = None
if "selected_project" not in st.session_state:
    st.session_state.selected_project = None
if "auth_mode" not in st.session_state:
    st.session_state.auth_mode = "login"
if "task_output" not in st.session_state:
    st.session_state.task_output = None
if "approved_requirements" not in st.session_state:
    st.session_state.approved_requirements = None
if "plan_output" not in st.session_state:
    st.session_state.plan_output = None
if "feasibility_output" not in st.session_state:
    st.session_state.feasibility_output = None
if "approved_plan" not in st.session_state:
    st.session_state.approved_plan = None
if "estimation_output" not in st.session_state:
    st.session_state.estimation_output = None
if "approved_estimation" not in st.session_state:
    st.session_state.approved_estimation = None
if "approved_feasibility" not in st.session_state:
    st.session_state.approved_feasibility = None
if "approved_plan" not in st.session_state:
    st.session_state.approved_plan = None
if "report_output" not in st.session_state:
    st.session_state.report_output = None


def reset_planning_pipeline():
    st.session_state.plan_output = None
    st.session_state.feasibility_output = None
    st.session_state.approved_plan = None
    st.session_state.approved_feasibility = None
    st.session_state.estimation_output = None
    st.session_state.approved_estimation = None
    st.session_state.report_output = None
    st.session_state.pop("hitl2_edit_mode", None)
    st.session_state.pop("hitl_est_edit_mode", None)
    st.session_state.pop("hitl2_plan_edit", None)
    st.session_state.pop("hitl2_feas_edit", None)
    st.session_state.pop("hitl2_est_edit", None)
 
# -------------------------------------------------------------
# Authentication Screen
# -------------------------------------------------------------
def render_auth_page():
    st.markdown('<div class="main-title" style="text-align: center;">⚡ AI-Powered POC Generator</div>', unsafe_allow_html=True)
    st.markdown('<div class="subtitle" style="text-align: center;">Transform client conversations into production-ready project plans.</div>', unsafe_allow_html=True)
 
    col1, col2, col3 = st.columns([1, 1.5, 1])
 
    with col2:
        st.markdown('<div class="glass-card">', unsafe_allow_html=True)
        st.markdown('<div class="accent-bar"></div>', unsafe_allow_html=True)
 
        if st.session_state.auth_mode == "login":
            st.subheader("Sign In")
            email = st.text_input("Email Address", placeholder="name@company.com", key="login_email")
            password = st.text_input("Password", type="password", placeholder="••••••••", key="login_password")
 
            if st.button("Log In", type="primary", use_container_width=True, key="login_btn"):
                if not email or not password:
                    st.error("Please fill in all fields.")
                else:
                    try:
                        res = db.sign_in(email, password)
                        st.session_state.user = res.user
                        st.success("Successfully logged in!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Login failed: {e}")
 
            st.markdown("---")
            if st.button("Don't have an account? Sign Up", use_container_width=True, key="goto_signup"):
                st.session_state.auth_mode = "signup"
                st.rerun()
 
        else:
            st.subheader("Create Account")
            email = st.text_input("Email Address", placeholder="name@company.com", key="signup_email")
            password = st.text_input("Password", type="password", placeholder="At least 6 characters", key="signup_password")
 
            if st.button("Sign Up", type="primary", use_container_width=True, key="signup_btn"):
                if not email or not password:
                    st.error("Please fill in all fields.")
                elif len(password) < 6:
                    st.error("Password must be at least 6 characters.")
                else:
                    try:
                        db.sign_up(email, password)
                        st.success("Account created! Please sign in.")
                        st.session_state.auth_mode = "login"
                        st.rerun()
                    except Exception as e:
                        st.error(f"Sign up failed: {e}")
 
            st.markdown("---")
            if st.button("Already have an account? Log In", use_container_width=True, key="goto_login"):
                st.session_state.auth_mode = "login"
                st.rerun()
 
        st.markdown('</div>', unsafe_allow_html=True)
 
# -------------------------------------------------------------
# Render Task Agent Results (HITL)
# -------------------------------------------------------------
def render_task_agent_section(transcript: str, project_id: str):
    st.markdown("---")
    st.markdown("### 🤖 Step 2: Task Identification Agent")
    st.markdown('<div class="glass-card">', unsafe_allow_html=True)
    st.markdown('<div class="accent-bar-green"></div>', unsafe_allow_html=True)
 
    col_run, col_status = st.columns([2, 1])
 
    with col_run:
        st.markdown("**Run the Task Agent** to extract requirements, pain points, constraints, and business goals from your transcript using Gemini AI.")
 
    with col_status:
        if st.session_state.task_output:
            st.markdown("<span class='status-badge status-completed'>✅ COMPLETED</span>", unsafe_allow_html=True)
        else:
            st.markdown("<span class='status-badge status-pending'>PENDING</span>", unsafe_allow_html=True)
 
    col_btn1, col_btn2 = st.columns([1, 3])
    with col_btn1:
        run_clicked = st.button("▶ Run Task Agent", type="primary", key="run_task_agent_btn")
 
    if run_clicked:
        with st.spinner("🤖 Gemini is analyzing the transcript..."):
            try:
                result = call_task_agent(transcript)
                st.session_state.task_output = result
                st.session_state.approved_requirements = None
                reset_planning_pipeline()
                st.success("✅ Task Agent completed successfully!")
                st.rerun()
            except Exception as e:
                st.error(f"Task Agent failed: {e}")
 
    # Display results if available
    if st.session_state.task_output:
        output = st.session_state.task_output
 
        st.markdown("#### 📋 Extracted Requirements — Please Review")
        
        tab1, tab2, tab3, tab4, tab5 = st.tabs(["🔴 Pain Points", "✅ Requirements", "⚠️ Constraints", "🎯 Business Goals", "💻 Tech Context"])
        
        with tab1:
            if output.pain_points:
                for item in output.pain_points:
                    st.markdown(f'<div class="pain-item">• {item}</div>', unsafe_allow_html=True)
            else:
                st.info("No pain points identified.")
        
        with tab2:
            if output.requirements:
                for item in output.requirements:
                    st.markdown(f'<div class="requirement-item">• {item}</div>', unsafe_allow_html=True)
            else:
                st.info("No requirements identified.")
        
        with tab3:
            if output.constraints:
                for item in output.constraints:
                    st.markdown(f'<div class="constraint-item">• {item}</div>', unsafe_allow_html=True)
            else:
                st.info("No constraints identified.")
        
        with tab4:
            if output.business_goals:
                for item in output.business_goals:
                    st.markdown(f'<div class="goal-item">• {item}</div>', unsafe_allow_html=True)
            else:
                st.info("No business goals identified.")
        
        with tab5:
            tech_ctx = getattr(output, 'technology_context', {}) or {}
            if tech_ctx:
                for category, description in tech_ctx.items():
                    label = category.replace("_", " ").title()
                    st.markdown(f'<div class="requirement-item"><strong>{label}:</strong> {description}</div>', unsafe_allow_html=True)
            else:
                st.info("No technology context identified.")
 
        # ---------------------------------------------------------
        # HITL Actions
        # ---------------------------------------------------------
        st.markdown("---")
        st.markdown("#### 🧑‍💼 Human-in-the-Loop Review")
        st.markdown("Review the extracted requirements above and choose an action:")
 
        hitl_col1, hitl_col2, hitl_col3 = st.columns(3)
 
        with hitl_col1:
            if st.button("✅ Approve & Continue", type="primary", use_container_width=True, key="approve_btn"):
                st.session_state.approved_requirements = output.model_dump()
                reset_planning_pipeline()
                st.success("Requirements approved! Ready for the Planning Agent.")
                st.rerun()
 
        with hitl_col2:
            if st.button("🔄 Regenerate", use_container_width=True, key="regen_btn"):
                with st.spinner("🤖 Regenerating..."):
                    try:
                        result = call_task_agent(transcript)
                        st.session_state.task_output = result
                        st.session_state.approved_requirements = None
                        reset_planning_pipeline()
                        st.rerun()
                    except Exception as e:
                        st.error(f"Regeneration failed: {e}")
 
        with hitl_col3:
            if st.button("✏️ Edit Manually", use_container_width=True, key="edit_btn"):
                st.session_state["hitl_edit_mode"] = True
 
        # Manual Edit Mode
        if st.session_state.get("hitl_edit_mode"):
            st.markdown("##### ✏️ Edit Requirements")
            edited_pain = st.text_area("Pain Points (one per line)", value="\n".join(output.pain_points), height=100, key="edit_pain")
            edited_reqs = st.text_area("Requirements (one per line)", value="\n".join(output.requirements), height=120, key="edit_reqs")
            edited_cons = st.text_area("Constraints (one per line)", value="\n".join(output.constraints), height=80, key="edit_cons")
            edited_goals = st.text_area("Business Goals (one per line)", value="\n".join(output.business_goals), height=100, key="edit_goals")
                    
            # Technology context editing
            tech_ctx = getattr(output, 'technology_context', {}) or {}
            tech_lines = [f"{k}: {v}" for k, v in tech_ctx.items()]
            edited_tech = st.text_area("Technology Context (key: value, one per line)", value="\n".join(tech_lines), height=100, key="edit_tech")
        
            if st.button("💾 Save Edits & Approve", type="primary", key="save_edits_btn"):
                from backend.schemas.task_schema import TaskAgentOutput
                # Parse technology context
                tech_dict = {}
                for line in edited_tech.split("\n"):
                    line = line.strip()
                    if ":" in line:
                        k, v = line.split(":", 1)
                        tech_dict[k.strip()] = v.strip()
                        
                edited_output = TaskAgentOutput(
                    pain_points=[x.strip() for x in edited_pain.split("\n") if x.strip()],
                    requirements=[x.strip() for x in edited_reqs.split("\n") if x.strip()],
                    constraints=[x.strip() for x in edited_cons.split("\n") if x.strip()],
                    business_goals=[x.strip() for x in edited_goals.split("\n") if x.strip()],
                    technology_context=tech_dict,
                )
                st.session_state.task_output = edited_output
                st.session_state.approved_requirements = edited_output.model_dump()
                st.session_state["hitl_edit_mode"] = False
                reset_planning_pipeline()
                st.success("✅ Edits saved and requirements approved!")
                st.rerun()
 
        # Show approved confirmation
        if st.session_state.approved_requirements:
            st.success("🎉 Requirements are **approved** and ready for the Planning Agent in the next phase!")
 
    st.markdown('</div>', unsafe_allow_html=True)


# -------------------------------------------------------------
# Render Planning Agent Results
# -------------------------------------------------------------
def render_planning_agent_section():
    st.markdown("---")
    st.markdown("### 🏗️ Step 3: Planning Agent")
    st.markdown('<div class="glass-card">', unsafe_allow_html=True)
    st.markdown('<div class="accent-bar-purple"></div>', unsafe_allow_html=True)

    col_run, col_status = st.columns([2, 1])

    with col_run:
        st.markdown(
            "**Run the Planning Agent** to generate a technical architecture, tech stack, "
            "and Mermaid diagram from your approved requirements."
        )

    with col_status:
        if st.session_state.plan_output:
            st.markdown("<span class='status-badge status-completed'>✅ COMPLETED</span>", unsafe_allow_html=True)
        else:
            st.markdown("<span class='status-badge status-pending'>PENDING</span>", unsafe_allow_html=True)

    if st.button("▶ Run Planning Agent", type="primary", key="run_planning_agent_btn"):
        with st.spinner("🏗️ Gemini is designing the architecture..."):
            try:
                _pid = (st.session_state.selected_project or {}).get("id")
                result = call_planning_agent(st.session_state.approved_requirements, project_id=_pid)
                st.session_state.plan_output = result
                st.session_state.feasibility_output = None
                st.session_state.approved_plan = None
                st.success("✅ Planning Agent completed successfully!")
                st.rerun()
            except Exception as e:
                st.error(f"Planning Agent failed: {e}")

    if st.session_state.plan_output:
        plan = st.session_state.plan_output

        st.markdown(f"#### 🧩 Architecture: **{plan.architecture_type}**")

        if plan.tech_stack:
            st.markdown("##### 🛠️ Tech Stack")
            for category, tech in plan.tech_stack.items():
                reason = plan.recommendation_reason.get(category, "")
                label = category.replace("_", " ").title()
                st.markdown(f"**{label}:** {tech}")
                if reason:
                    st.caption(reason)

        summary = plan.architecture_summary
        st.markdown("##### 📐 Architecture Summary")
        st.markdown(f"**Overview:** {summary.overview}")
        st.markdown(f"**Workflow:** {summary.workflow}")
        st.markdown(f"**Data Flow:** {summary.data_flow}")

        if plan.reference_docs:
            st.markdown("##### 📚 Reference Docs")
            for doc in plan.reference_docs:
                st.markdown(f"- [{doc.title}]({doc.url})")

        if plan.mermaid_diagram:
            st.markdown("##### 🗺️ Architecture Diagram")
            with st.expander("📊 View Architecture Diagram", expanded=True):
                render_mermaid_diagram(plan.mermaid_diagram)
            with st.expander("📝 Diagram Source (Mermaid)", expanded=False):
                st.code(plan.mermaid_diagram, language="mermaid")

    st.markdown('</div>', unsafe_allow_html=True)


# -------------------------------------------------------------
# Render Feasibility Agent + HITL #2
# -------------------------------------------------------------
def render_feasibility_section():
    st.markdown("---")
    st.markdown("### 🔍 Step 4: Feasibility Study")
    st.markdown('<div class="glass-card">', unsafe_allow_html=True)
    st.markdown('<div class="accent-bar"></div>', unsafe_allow_html=True)

    col_run, col_status = st.columns([2, 1])

    with col_run:
        st.markdown(
            "**Run the Feasibility Agent** to evaluate technical risks, complexity, "
            "and viability of the proposed plan."
        )

    with col_status:
        if st.session_state.feasibility_output:
            st.markdown("<span class='status-badge status-completed'>✅ COMPLETED</span>", unsafe_allow_html=True)
        else:
            st.markdown("<span class='status-badge status-pending'>PENDING</span>", unsafe_allow_html=True)

    if st.button("▶ Run Feasibility Agent", type="primary", key="run_feasibility_agent_btn"):
        with st.spinner("🔍 Gemini is assessing feasibility..."):
            try:
                result = call_feasibility_agent(
                    st.session_state.approved_requirements,
                    st.session_state.plan_output.model_dump(),
                )
                st.session_state.feasibility_output = result
                st.session_state.approved_plan = None
                st.success("✅ Feasibility Agent completed successfully!")
                st.rerun()
            except Exception as e:
                st.error(f"Feasibility Agent failed: {e}")

    if st.session_state.feasibility_output:
        feasibility = st.session_state.feasibility_output

        st.markdown("#### 📊 Feasibility Assessment")

        metric_col1, metric_col2, metric_col3 = st.columns(3)
        with metric_col1:
            st.markdown('<div class="metric-card">', unsafe_allow_html=True)
            st.markdown('<div class="metric-label">Complexity</div>', unsafe_allow_html=True)
            st.markdown(
                level_badge_html(feasibility.complexity_level, COMPLEXITY_BADGES),
                unsafe_allow_html=True,
            )
            st.markdown('</div>', unsafe_allow_html=True)
        arch_confidence = getattr(feasibility, "architecture_confidence", None)
        feas_confidence = getattr(feasibility, "feasibility_confidence", None)

        with metric_col2:
            st.markdown('<div class="metric-card">', unsafe_allow_html=True)
            st.markdown('<div class="metric-label">Architecture Confidence</div>', unsafe_allow_html=True)
            if arch_confidence:
                st.markdown(level_badge_html(arch_confidence, CONFIDENCE_BADGES), unsafe_allow_html=True)
            else:
                st.caption("Re-run agent to refresh")
            st.markdown('</div>', unsafe_allow_html=True)
        with metric_col3:
            st.markdown('<div class="metric-card">', unsafe_allow_html=True)
            st.markdown('<div class="metric-label">Feasibility Confidence</div>', unsafe_allow_html=True)
            if feas_confidence:
                st.markdown(level_badge_html(feas_confidence, CONFIDENCE_BADGES), unsafe_allow_html=True)
            else:
                st.caption("Re-run agent to refresh")
            st.markdown('</div>', unsafe_allow_html=True)

        st.markdown(f"**Summary:** {feasibility.feasibility_summary}")

        if feasibility.technical_risks:
            st.markdown("##### ⚠️ Technical Risks")
            for risk in feasibility.technical_risks:
                with st.expander(f"🔴 {risk.risk}", expanded=False):
                    st.markdown(f"**Impact:** {risk.impact}")
                    st.markdown(f"**Mitigation:** {risk.mitigation}")
        else:
            st.info("No technical risks identified.")

    st.markdown('</div>', unsafe_allow_html=True)


# -------------------------------------------------------------
# Render Estimation Agent Results + HITL
# -------------------------------------------------------------
def render_estimation_section():
    st.markdown("---")
    st.markdown("### 📊 Step 5: Effort Estimation")
    st.markdown('<div class="glass-card">', unsafe_allow_html=True)
    st.markdown('<div class="accent-bar-green"></div>', unsafe_allow_html=True)

    col_run, col_status = st.columns([2, 1])

    with col_run:
        st.markdown(
            "**Run the Estimation Agent** to generate detailed development effort estimates "
            "broken down by module, feature, and technology (HTML, ReactJS, Python, AI)."
        )

    with col_status:
        if st.session_state.estimation_output:
            st.markdown("<span class='status-badge status-completed'>✅ COMPLETED</span>", unsafe_allow_html=True)
        else:
            st.markdown("<span class='status-badge status-pending'>PENDING</span>", unsafe_allow_html=True)

    if st.button("▶ Run Estimation Agent", type="primary", key="run_estimation_agent_btn"):
        with st.spinner("📊 Gemini is calculating effort estimates..."):
            try:
                _pid = (st.session_state.selected_project or {}).get("id")
                result = call_estimation_agent(
                    st.session_state.approved_requirements,
                    st.session_state.plan_output.model_dump(),
                    st.session_state.feasibility_output.model_dump(),
                    project_id=_pid,
                )
                st.session_state.estimation_output = result
                st.session_state.approved_estimation = None
                st.success("✅ Estimation Agent completed successfully!")
                st.rerun()
            except Exception as e:
                st.error(f"Estimation Agent failed: {e}")

    if st.session_state.estimation_output:
        estimation = st.session_state.estimation_output

        st.markdown("#### 📋 Development Effort Estimation")

        # Get dynamic tech categories
        tech_categories = estimation.tech_categories or []

        # Build DataFrame for display and export
        rows = []
        for idx, item in enumerate(estimation.estimations, start=1):
            row = {
                "No": f"A.{idx-1}",
                "Functionality Type": item.functionality_type,
                "Module": item.module,
                "Features": item.feature,
                "Complexity": item.complexity,
                "Interface Type": item.interface_type,
            }
            # Add dynamic tech hours columns
            for cat in tech_categories:
                row[cat] = item.tech_hours.get(cat, 0)
            row["Remarks Tech"] = item.tech_remarks
            row["Remarks BA"] = item.ba_remarks
            rows.append(row)

        # Add totals row
        totals = estimation.totals
        totals_row = {
            "No": "",
            "Functionality Type": "",
            "Module": "",
            "Features": "**TOTALS**",
            "Complexity": "",
            "Interface Type": "",
        }
        for cat in tech_categories:
            totals_row[cat] = totals.tech_totals.get(cat, 0)
        totals_row["Remarks Tech"] = ""
        totals_row["Remarks BA"] = ""
        rows.append(totals_row)

        df = pd.DataFrame(rows)

        # Build dynamic column config
        column_config = {
            "No": st.column_config.TextColumn("No", width="small"),
            "Functionality Type": st.column_config.TextColumn("Functionality Type", width="medium"),
            "Module": st.column_config.TextColumn("Module", width="medium"),
            "Features": st.column_config.TextColumn("Features", width="large"),
            "Complexity": st.column_config.TextColumn("Complexity", width="small"),
            "Interface Type": st.column_config.TextColumn("Interface Type", width="medium"),
        }
        for cat in tech_categories:
            column_config[cat] = st.column_config.NumberColumn(cat, width="small")
        column_config["Remarks Tech"] = st.column_config.TextColumn("Remarks Tech", width="medium")
        column_config["Remarks BA"] = st.column_config.TextColumn("Remarks BA", width="medium")

        # Display styled table
        st.dataframe(
            df,
            use_container_width=True,
            hide_index=True,
            column_config=column_config,
        )

        # Grand total display
        st.markdown(f"**Grand Total: {totals.grand_total_hours} hours**")

        # Excel download
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
            df.to_excel(writer, index=False, sheet_name="Estimation")
        buffer.seek(0)

        st.download_button(
            label="📥 Download Estimation as Excel",
            data=buffer,
            file_name="effort_estimation.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
            key="dl_est_excel",
        )

    st.markdown('</div>', unsafe_allow_html=True)


# -------------------------------------------------------------
# Unified HITL #2: Review Plan + Feasibility + Estimation
# -------------------------------------------------------------
def render_hitl2_section():
    st.markdown("---")
    st.markdown("### 🧑‍💼 HITL #2: Final Review")
    st.markdown('<div class="glass-card">', unsafe_allow_html=True)
    st.markdown('<div class="accent-bar-green"></div>', unsafe_allow_html=True)

    st.markdown(
        "Review and approve **Planning**, **Feasibility**, and **Estimation** outputs before generating the final report."
    )

    # Show summary tabs
    tab_plan, tab_feas, tab_est = st.tabs(["🏗️ Plan", "🔍 Feasibility", "📊 Estimation"])

    with tab_plan:
        plan = st.session_state.plan_output
        st.markdown(f"**Architecture:** {plan.architecture_type}")
        if plan.tech_stack:
            st.json(plan.tech_stack)
        summary = plan.architecture_summary
        st.markdown(f"**Overview:** {summary.overview}")
        st.markdown(f"**Workflow:** {summary.workflow}")
        st.markdown(f"**Data Flow:** {summary.data_flow}")

    with tab_feas:
        feas = st.session_state.feasibility_output
        st.markdown(f"**Complexity:** {feas.complexity_level}")
        st.markdown(f"**Summary:** {feas.feasibility_summary}")
        if feas.technical_risks:
            for risk in feas.technical_risks:
                st.markdown(f"- **{risk.risk}** — Impact: {risk.impact}")

    with tab_est:
        est = st.session_state.estimation_output
        rows = []
        for idx, item in enumerate(est.estimations, start=1):
            rows.append({
                "No": f"A.{idx-1}",
                "Functionality Type": item.functionality_type,
                "Module": item.module,
                "Features": item.feature,
                "Complexity": item.complexity,
                "HTML": item.html_hours,
                "ReactJS": item.react_hours,
                "Python": item.python_hours,
                "AI": item.ai_hours,
            })
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        totals = est.totals
        st.markdown(
            f"**Totals:** HTML={totals.html_hours}  ReactJS={totals.react_hours}  Python={totals.python_hours}  AI={totals.ai_hours}"
        )

    # Action buttons
    st.markdown("---")

    c1, c2, c3, c4, c5 = st.columns(5)

    with c1:
        if st.button("✅ Approve Everything", type="primary", use_container_width=True, key="hitl2_approve_btn"):
            st.session_state.approved_plan = st.session_state.plan_output.model_dump()
            st.session_state.approved_feasibility = st.session_state.feasibility_output.model_dump()
            st.session_state.approved_estimation = st.session_state.estimation_output.model_dump()
            st.session_state.pop("hitl2_edit_mode", None)
            st.success("All outputs approved! Generating report...")
            st.rerun()

    with c2:
        if st.button("🔄 Regenerate Plan", use_container_width=True, key="hitl2_regen_plan_btn"):
            with st.spinner("🏗️ Regenerating plan..."):
                try:
                    _pid = (st.session_state.selected_project or {}).get("id")
                    result = call_planning_agent(st.session_state.approved_requirements, project_id=_pid)
                    st.session_state.plan_output = result
                    st.session_state.feasibility_output = None
                    st.session_state.estimation_output = None
                    st.session_state.approved_plan = None
                    st.session_state.approved_feasibility = None
                    st.session_state.approved_estimation = None
                    st.session_state.report_output = None
                    st.rerun()
                except Exception as e:
                    st.error(f"Plan regeneration failed: {e}")

    with c3:
        if st.button("🔁 Re-run Feasibility", use_container_width=True, key="hitl2_rerun_feas_btn"):
            with st.spinner("🔍 Re-running feasibility..."):
                try:
                    result = call_feasibility_agent(
                        st.session_state.approved_requirements,
                        st.session_state.plan_output.model_dump(),
                    )
                    st.session_state.feasibility_output = result
                    st.session_state.estimation_output = None
                    st.session_state.approved_feasibility = None
                    st.session_state.approved_estimation = None
                    st.session_state.report_output = None
                    st.rerun()
                except Exception as e:
                    st.error(f"Feasibility re-run failed: {e}")

    with c4:
        if st.button("📊 Regenerate Estimation", use_container_width=True, key="hitl2_regen_est_btn"):
            with st.spinner("📊 Regenerating estimation..."):
                try:
                    _pid = (st.session_state.selected_project or {}).get("id")
                    result = call_estimation_agent(
                        st.session_state.approved_requirements,
                        st.session_state.plan_output.model_dump(),
                        st.session_state.feasibility_output.model_dump(),
                        project_id=_pid,
                    )
                    st.session_state.estimation_output = result
                    st.session_state.approved_estimation = None
                    st.session_state.report_output = None
                    st.rerun()
                except Exception as e:
                    st.error(f"Estimation regeneration failed: {e}")

    with c5:
        if st.button("✏️ Edit Manually", use_container_width=True, key="hitl2_edit_btn"):
            st.session_state["hitl2_edit_mode"] = True

    # Edit Manually Mode
    if st.session_state.get("hitl2_edit_mode"):
        st.markdown("---")
        st.markdown("#### ✏️ Edit Outputs Manually")

        edit_plan, edit_feas, edit_est = st.tabs(["Edit Plan", "Edit Feasibility", "Edit Estimation"])

        with edit_plan:
            plan_json = st.text_area(
                "Plan JSON (edit carefully)",
                value=json.dumps(st.session_state.plan_output.model_dump(), indent=2),
                height=300,
                key="hitl2_plan_edit",
            )

        with edit_feas:
            feas_json = st.text_area(
                "Feasibility JSON (edit carefully)",
                value=json.dumps(st.session_state.feasibility_output.model_dump(), indent=2),
                height=300,
                key="hitl2_feas_edit",
            )

        with edit_est:
            est = st.session_state.estimation_output
            est_rows = []
            for idx, item in enumerate(est.estimations, start=1):
                est_rows.append({
                    "No": f"A.{idx-1}",
                    "Functionality Type": item.functionality_type,
                    "Module": item.module,
                    "Features": item.feature,
                    "Complexity": item.complexity,
                    "Interface Type": item.interface_type,
                    "HTML": item.html_hours,
                    "ReactJS": item.react_hours,
                    "Python": item.python_hours,
                    "AI": item.ai_hours,
                    "Remarks Tech": item.tech_remarks,
                    "Remarks BA": item.ba_remarks,
                })
            est_df = pd.DataFrame(est_rows)
            edited_est_df = st.data_editor(est_df, num_rows="dynamic", use_container_width=True, key="hitl2_est_edit_df")

        if st.button("💾 Save Edits & Approve", type="primary", key="hitl2_save_edits_btn"):
            import json
            try:
                from backend.schemas.plan_schema import PlanningAgentOutput
                from backend.schemas.feasibility_schema import FeasibilityAgentOutput
                from backend.schemas.estimation_schema import EstimationAgentOutput, EstimationItem, EstimationTotals

                new_plan = PlanningAgentOutput(**json.loads(plan_json))
                new_feas = FeasibilityAgentOutput(**json.loads(feas_json))

                # Rebuild estimation from edited dataframe
                new_estimations = []
                for _, row in edited_est_df.iterrows():
                    new_estimations.append(EstimationItem(
                        functionality_type=str(row.get("Functionality Type", "")),
                        module=str(row.get("Module", "")),
                        feature=str(row.get("Features", "")),
                        complexity=str(row.get("Complexity", "")),
                        interface_type=str(row.get("Interface Type", "")),
                        html_hours=int(row.get("HTML", 0) or 0),
                        react_hours=int(row.get("ReactJS", 0) or 0),
                        python_hours=int(row.get("Python", 0) or 0),
                        ai_hours=int(row.get("AI", 0) or 0),
                        tech_remarks=str(row.get("Remarks Tech", "")),
                        ba_remarks=str(row.get("Remarks BA", "")),
                    ))

                total_html = sum(e.html_hours for e in new_estimations)
                total_react = sum(e.react_hours for e in new_estimations)
                total_python = sum(e.python_hours for e in new_estimations)
                total_ai = sum(e.ai_hours for e in new_estimations)

                new_est = EstimationAgentOutput(
                    estimations=new_estimations,
                    totals=EstimationTotals(
                        html_hours=total_html,
                        react_hours=total_react,
                        python_hours=total_python,
                        ai_hours=total_ai,
                    ),
                )

                st.session_state.plan_output = new_plan
                st.session_state.feasibility_output = new_feas
                st.session_state.estimation_output = new_est
                st.session_state.approved_plan = new_plan.model_dump()
                st.session_state.approved_feasibility = new_feas.model_dump()
                st.session_state.approved_estimation = new_est.model_dump()
                st.session_state["hitl2_edit_mode"] = False
                st.success("✅ Edits saved and all outputs approved!")
                st.rerun()
            except Exception as e:
                st.error(f"Failed to save edits: {e}")

    if st.session_state.approved_estimation and not st.session_state.get("hitl2_edit_mode"):
        st.success("🎉 All outputs are **approved**! Report generation is the next phase.")

    st.markdown('</div>', unsafe_allow_html=True)


# -------------------------------------------------------------
# Report Agent Section
# -------------------------------------------------------------
def render_report_section():
    st.markdown("---")
    st.markdown("### 📋 Step 7: Final Report")
    st.markdown('<div class="glass-card">', unsafe_allow_html=True)
    st.markdown('<div class="accent-bar-purple"></div>', unsafe_allow_html=True)

    if not st.session_state.report_output:
        if st.button("▶ Generate Final Report", type="primary", use_container_width=True, key="run_report_btn"):
            approved_req = st.session_state.approved_requirements or {}
            approved_plan = st.session_state.approved_plan or (st.session_state.plan_output.model_dump() if st.session_state.plan_output else {})
            approved_feas = st.session_state.approved_feasibility or (st.session_state.feasibility_output.model_dump() if st.session_state.feasibility_output else {})
            approved_est = st.session_state.approved_estimation or (st.session_state.estimation_output.model_dump() if st.session_state.estimation_output else {})

            st.session_state.report_output = {
                "requirements": approved_req,
                "plan": approved_plan,
                "feasibility": approved_feas,
                "estimation": approved_est,
            }
            st.success("✅ Final Report compiled successfully!")
            st.rerun()
    else:
        report = st.session_state.report_output
        req_data = report.get("requirements", {})
        plan_data = report.get("plan", {})
        feas_data = report.get("feasibility", {})
        est_data = report.get("estimation", {})

        # ── 1. REQUIREMENTS (same as Task Agent output) ──
        st.markdown("#### 📋 Requirements Analysis")
        if req_data:
            tab1, tab2, tab3, tab4, tab5 = st.tabs(["🔴 Pain Points", "✅ Requirements", "⚠️ Constraints", "🎯 Business Goals", "💻 Tech Context"])
            with tab1:
                for item in req_data.get("pain_points", []):
                    st.markdown(f'<div class="requirement-item">• {item}</div>', unsafe_allow_html=True)
            with tab2:
                for item in req_data.get("requirements", []):
                    st.markdown(f'<div class="requirement-item">• {item}</div>', unsafe_allow_html=True)
            with tab3:
                for item in req_data.get("constraints", []):
                    st.markdown(f'<div class="requirement-item">• {item}</div>', unsafe_allow_html=True)
            with tab4:
                for item in req_data.get("business_goals", []):
                    st.markdown(f'<div class="requirement-item">• {item}</div>', unsafe_allow_html=True)
            with tab5:
                tech_ctx = req_data.get("technology_context", {})
                if tech_ctx:
                    for category, description in tech_ctx.items():
                        label = category.replace("_", " ").title()
                        st.markdown(f'<div class="requirement-item"><strong>{label}:</strong> {description}</div>', unsafe_allow_html=True)
                else:
                    st.info("No technology context extracted.")
        else:
            st.info("No requirements data.")

        st.markdown("---")

        # ── 2. PLANNING (same as Planning Agent output) ──
        st.markdown("#### 🏗️ Architecture & Planning")
        if plan_data:
            st.markdown(f"##### 🧩 Architecture: **{plan_data.get('architecture_type', 'N/A')}**")

            tech_stack = plan_data.get("tech_stack", {})
            rec_reasons = plan_data.get("recommendation_reason", {})
            if tech_stack:
                st.markdown("##### 🛠️ Tech Stack")
                for category, tech in tech_stack.items():
                    reason = rec_reasons.get(category, "")
                    label = category.replace("_", " ").title()
                    st.markdown(f"**{label}:** {tech}")
                    if reason:
                        st.caption(reason)

            arch_summary = plan_data.get("architecture_summary", {})
            if arch_summary:
                st.markdown("##### 📐 Architecture Summary")
                st.markdown(f"**Overview:** {arch_summary.get('overview', '')}")
                st.markdown(f"**Workflow:** {arch_summary.get('workflow', '')}")
                st.markdown(f"**Data Flow:** {arch_summary.get('data_flow', '')}")

            ref_docs = plan_data.get("reference_docs", [])
            if ref_docs:
                st.markdown("##### 📚 Reference Docs")
                for doc in ref_docs:
                    st.markdown(f"- [{doc.get('title', '')}]({doc.get('url', '')})")

            mermaid = plan_data.get("mermaid_diagram", "")
            if mermaid:
                st.markdown("##### 🗺️ Architecture Diagram")
                with st.expander("📊 View Architecture Diagram", expanded=True):
                    render_mermaid_diagram(mermaid)
                with st.expander("📝 Diagram Source (Mermaid)", expanded=False):
                    st.code(mermaid, language="mermaid")
        else:
            st.info("No planning data.")

        st.markdown("---")

        # ── 3. FEASIBILITY (same as Feasibility Agent output) ──
        st.markdown("#### 🔍 Feasibility Assessment")
        if feas_data:
            metric_col1, metric_col2, metric_col3 = st.columns(3)
            with metric_col1:
                st.markdown('<div class="metric-card">', unsafe_allow_html=True)
                st.markdown('<div class="metric-label">Complexity</div>', unsafe_allow_html=True)
                st.markdown(level_badge_html(feas_data.get("complexity_level", ""), COMPLEXITY_BADGES), unsafe_allow_html=True)
                st.markdown('</div>', unsafe_allow_html=True)

            arch_confidence = feas_data.get("architecture_confidence")
            feas_confidence = feas_data.get("feasibility_confidence")

            with metric_col2:
                st.markdown('<div class="metric-card">', unsafe_allow_html=True)
                st.markdown('<div class="metric-label">Architecture Confidence</div>', unsafe_allow_html=True)
                if arch_confidence:
                    st.markdown(level_badge_html(arch_confidence, CONFIDENCE_BADGES), unsafe_allow_html=True)
                else:
                    st.caption("N/A")
                st.markdown('</div>', unsafe_allow_html=True)

            with metric_col3:
                st.markdown('<div class="metric-card">', unsafe_allow_html=True)
                st.markdown('<div class="metric-label">Feasibility Confidence</div>', unsafe_allow_html=True)
                if feas_confidence:
                    st.markdown(level_badge_html(feas_confidence, CONFIDENCE_BADGES), unsafe_allow_html=True)
                else:
                    st.caption("N/A")
                st.markdown('</div>', unsafe_allow_html=True)

            feas_summary = feas_data.get("feasibility_summary", "")
            if feas_summary:
                st.markdown(f"**Summary:** {feas_summary}")

            risks = feas_data.get("technical_risks", [])
            if risks:
                st.markdown("##### ⚠️ Technical Risks")
                for risk in risks:
                    with st.expander(f"🔴 {risk.get('risk', '')}", expanded=False):
                        st.markdown(f"**Impact:** {risk.get('impact', '')}")
                        st.markdown(f"**Mitigation:** {risk.get('mitigation', '')}")
            else:
                st.info("No technical risks identified.")
        else:
            st.info("No feasibility data.")

        st.markdown("---")

        # ── 4. ESTIMATION (same as Estimation Agent output) ──
        st.markdown("#### 📊 Effort Estimation")
        if est_data:
            estimations = est_data.get("estimations", [])
            tech_categories = est_data.get("tech_categories", [])
            totals = est_data.get("totals", {})

            if estimations:
                rows = []
                for idx, item in enumerate(estimations, start=1):
                    row = {
                        "No": f"A.{idx-1}",
                        "Functionality Type": item.get("functionality_type", ""),
                        "Module": item.get("module", ""),
                        "Features": item.get("feature", ""),
                        "Complexity": item.get("complexity", ""),
                        "Interface Type": item.get("interface_type", ""),
                    }
                    for cat in tech_categories:
                        row[cat] = item.get("tech_hours", {}).get(cat, 0)
                    row["Remarks Tech"] = item.get("tech_remarks", "")
                    row["Remarks BA"] = item.get("ba_remarks", "")
                    rows.append(row)

                totals_row = {
                    "No": "", "Functionality Type": "", "Module": "",
                    "Features": "**TOTALS**", "Complexity": "", "Interface Type": "",
                }
                for cat in tech_categories:
                    totals_row[cat] = totals.get("tech_totals", {}).get(cat, 0)
                totals_row["Remarks Tech"] = ""
                totals_row["Remarks BA"] = ""
                rows.append(totals_row)

                df = pd.DataFrame(rows)

                column_config = {
                    "No": st.column_config.TextColumn("No", width="small"),
                    "Functionality Type": st.column_config.TextColumn("Functionality Type", width="medium"),
                    "Module": st.column_config.TextColumn("Module", width="medium"),
                    "Features": st.column_config.TextColumn("Features", width="large"),
                    "Complexity": st.column_config.TextColumn("Complexity", width="small"),
                    "Interface Type": st.column_config.TextColumn("Interface Type", width="medium"),
                }
                for cat in tech_categories:
                    column_config[cat] = st.column_config.NumberColumn(cat, width="small")
                column_config["Remarks Tech"] = st.column_config.TextColumn("Remarks Tech", width="medium")
                column_config["Remarks BA"] = st.column_config.TextColumn("Remarks BA", width="medium")

                st.dataframe(df, use_container_width=True, hide_index=True, column_config=column_config)
                st.markdown(f"**Grand Total: {totals.get('grand_total_hours', 0)} hours**")

                buffer = io.BytesIO()
                with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
                    df.to_excel(writer, index=False, sheet_name="Estimation")
                buffer.seek(0)
                st.download_button(
                    label="📥 Download Estimation as Excel",
                    data=buffer,
                    file_name="effort_estimation.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True,
                    key="dl_report_est_excel",
                )
            else:
                st.info("No estimation data.")
        else:
            st.info("No estimation data.")

        # ── 5. DOWNLOADS ──
        st.markdown("---")
        st.markdown("#### 📥 Download Report")

        json_buffer = generate_json(report)
        d1, d2 = st.columns(2)

        with d1:
            st.download_button(
                label="📋 JSON (.json)",
                data=json_buffer,
                file_name="project_report.json",
                mime="application/json",
                use_container_width=True,
                key="dl_report_json",
            )

        with d2:
            md_buffer = generate_markdown(report)
            st.download_button(
                label="📝 Markdown (.md)",
                data=md_buffer,
                file_name="project_report.md",
                mime="text/markdown",
                use_container_width=True,
                key="dl_report_md",
            )

    st.markdown('</div>', unsafe_allow_html=True)


# -------------------------------------------------------------
# Main Application Dashboard
# -------------------------------------------------------------
def render_dashboard():
    user = st.session_state.user
 
    # --- Sidebar ---
    st.sidebar.markdown("### 👤 Active User")
    st.sidebar.info(f"{user.email}")
 
    if st.sidebar.button("Sign Out", use_container_width=True, key="signout_btn"):
        try:
            db.sign_out()
        except Exception:
            pass
        st.session_state.user = None
        st.session_state.selected_project = None
        st.session_state.task_output = None
        st.session_state.approved_requirements = None
        st.session_state["_transcript_exists"] = False
        reset_planning_pipeline()
        st.rerun()

    st.sidebar.markdown("---")
    st.sidebar.markdown("### 📁 Project Management")
 
    try:
        projects = _cached_get_projects(user.id)
    except Exception as e:
        st.sidebar.error(f"Failed to fetch projects: {e}")
        projects = []
 
    project_options = ["-- Select a Project --"] + [p["name"] for p in projects]
 
    selected_index = 0
    if st.session_state.selected_project:
        for idx, p in enumerate(projects):
            if p["id"] == st.session_state.selected_project["id"]:
                selected_index = idx + 1
                break
 
    # Store for on_change callback (callbacks cannot read local variables)
    st.session_state["_projects_list"] = projects

    def _on_project_change():
        chosen = st.session_state["project_selector"]
        _projects = st.session_state.get("_projects_list", [])
        if chosen == "-- Select a Project --":
            st.session_state.selected_project = None
            st.session_state.task_output = None
            st.session_state.approved_requirements = None
            reset_planning_pipeline()
        else:
            sel = next((p for p in _projects if p["name"] == chosen), None)
            if sel is None:
                st.session_state.selected_project = None
            elif (
                not st.session_state.selected_project
                or st.session_state.selected_project["id"] != sel["id"]
            ):
                st.session_state.selected_project = sel
                st.session_state.task_output = None
                st.session_state.approved_requirements = None
                st.session_state["_transcript_exists"] = False
                reset_planning_pipeline()

    st.sidebar.selectbox(
        "Select Active Project",
        options=project_options,
        index=selected_index,
        key="project_selector",
        on_change=_on_project_change,
    )
 
    st.sidebar.markdown("#### Create New Project")
    new_proj_name = st.sidebar.text_input("Project Name", placeholder="e.g. Client X - Core POC", key="new_proj_input")
    if st.sidebar.button("Add Project", type="primary", use_container_width=True, key="add_proj_btn"):
        if not new_proj_name.strip():
            st.sidebar.warning("Please enter a project name.")
        else:
            try:
                new_project = db.create_project(user.id, new_proj_name.strip())
                _cached_get_projects.clear()
                st.session_state.selected_project = new_project
                st.session_state.task_output = None
                st.session_state.approved_requirements = None
                reset_planning_pipeline()
                st.sidebar.success(f"Project '{new_proj_name}' created!")
                st.rerun()
            except Exception as e:
                st.sidebar.error(f"Failed to create project: {e}")
 
    # --- Reference Document Upload (RAG) ---
    st.sidebar.markdown("---")
    st.sidebar.markdown("### 📚 Reference Documents")
    st.sidebar.caption("Optional — upload SOW, BRD, specs, or prior estimates to enrich AI context")

    if st.session_state.selected_project:
        _rag_pid = st.session_state.selected_project["id"]

        uploaded_ref_files = st.sidebar.file_uploader(
            "Upload reference docs",
            type=["pdf", "docx", "txt"],
            accept_multiple_files=True,
            key="ref_doc_uploader",
            label_visibility="collapsed",
        )

        if uploaded_ref_files:
            if st.sidebar.button("📤 Ingest Documents", use_container_width=True, key="ingest_docs_btn"):
                for _uf in uploaded_ref_files:
                    _ext = _uf.name.rsplit(".", 1)[-1].lower()
                    with st.sidebar:
                        with st.spinner(f"Ingesting {_uf.name}…"):
                            _res = ingest_document(_rag_pid, _uf.read(), _uf.name, _ext)
                    if _res["success"]:
                        _cached_list_documents.clear()
                        st.sidebar.success(f"✅ {_uf.name}: {_res['chunks_inserted']} chunks")
                    else:
                        st.sidebar.error(f"❌ {_uf.name}: {_res.get('error', 'Failed')}")

        try:
            _existing_docs = _cached_list_documents(_rag_pid)
            if _existing_docs:
                st.sidebar.markdown("**Indexed docs:**")
                for _rdoc in _existing_docs:
                    _rc1, _rc2 = st.sidebar.columns([5, 1])
                    _rc1.caption(f"📄 {_rdoc['document_name'][:28]}")
                    if _rc2.button("✕", key=f"del_rdoc_{_rag_pid}_{_rdoc['document_name']}"):
                        delete_project_documents(_rag_pid, _rdoc["document_name"])
                        _cached_list_documents.clear()
                        st.rerun()
            else:
                st.sidebar.caption("No documents indexed yet.")
        except Exception:
            st.sidebar.caption("Could not load document list.")
    else:
        st.sidebar.caption("Select a project to upload documents.")

    # --- Pipeline status in sidebar ---
    st.sidebar.markdown("---")
    st.sidebar.markdown("### ⚡ Pipeline Status")

    # Use session state flag set by the transcript section — avoids a sidebar Supabase call
    transcript_done = bool(st.session_state.get("_transcript_exists", False))
    task_done = bool(st.session_state.task_output)
    approved_done = bool(st.session_state.approved_requirements)
    plan_done = bool(st.session_state.plan_output)
    feasibility_done = bool(st.session_state.feasibility_output)
    feasibility_approved_done = bool(st.session_state.get("approved_feasibility"))
    estimation_done = bool(st.session_state.estimation_output)
    estimation_approved_done = bool(st.session_state.approved_estimation)
    report_done = bool(st.session_state.report_output)

    st.sidebar.markdown(f"{'✅' if transcript_done else '⬜'} Transcript Upload")
    st.sidebar.markdown(f"{'✅' if task_done else '⬜'} Task Agent")
    st.sidebar.markdown(f"{'✅' if approved_done else '⬜'} HITL #1 (Requirements)")
    st.sidebar.markdown(f"{'✅' if plan_done else '⬜'} Planning Agent")
    st.sidebar.markdown(f"{'✅' if feasibility_done else '⬜'} Feasibility Agent")
    st.sidebar.markdown(f"{'✅' if feasibility_approved_done else '⬜'} HITL #2 (Feasibility)")
    st.sidebar.markdown(f"{'✅' if estimation_done else '⬜'} Estimation Agent")
    st.sidebar.markdown(f"{'✅' if estimation_approved_done else '⬜'} HITL #3 (Estimation)")
    st.sidebar.markdown(f"{'✅' if report_done else '⬜'} Report Agent")
 
    # --- Main Content ---
    st.markdown('<div class="main-title">⚡ AI-Powered POC Generator</div>', unsafe_allow_html=True)
    st.markdown('<div class="subtitle">Transform client conversations into production-ready project plans.</div>', unsafe_allow_html=True)
 
    if not st.session_state.selected_project:
        st.markdown('<div class="glass-card">', unsafe_allow_html=True)
        st.markdown('<div class="accent-bar"></div>', unsafe_allow_html=True)
        st.info("👈 Please select an existing project or create a new one from the sidebar to begin.")
        st.markdown('</div>', unsafe_allow_html=True)
        return
 
    project = st.session_state.selected_project
    st.markdown(f"### 📂 Active Project: **{project['name']}**")
 
    # ── Step 1: Transcript Upload ──────────────────────────────
    st.markdown("### 📝 Step 1: Upload Client Meeting Transcript")
    col_left, col_right = st.columns([1.2, 0.8])
 
    existing_transcript = ""
    try:
        transcript_record = _cached_get_transcript(project["id"])
        if transcript_record:
            existing_transcript = transcript_record.get("content", "")
        st.session_state["_transcript_exists"] = bool(existing_transcript.strip())
    except Exception as e:
        st.error(f"Error fetching transcript: {e}")
        st.session_state["_transcript_exists"] = False
 
    with col_left:
        st.markdown('<div class="glass-card">', unsafe_allow_html=True)
        st.markdown('<div class="accent-bar-purple"></div>', unsafe_allow_html=True)
        st.markdown("#### 📄 Transcript Input")
 
        uploaded_file = st.file_uploader(
            "Upload Meeting Transcript (PDF, DOCX, or TXT)",
            type=["txt", "pdf", "docx"],
            key="transcript_uploader"
        )
 
        pasted_text = st.text_area(
            "Or Paste Transcript here",
            value=existing_transcript if not uploaded_file else "",
            height=250,
            placeholder="Client: We need a system that registers users via email...\nPartner: Understood...",
            key="transcript_paste"
        )
 
        transcript_content = ""
        if uploaded_file is not None:
            try:
                file_bytes = uploaded_file.read()
                file_ext = uploaded_file.name.rsplit(".", 1)[-1].lower() if "." in uploaded_file.name else "txt"
                # Use extract_text to handle PDF, DOCX, and TXT formats
                transcript_content = extract_text(file_bytes, file_ext)
                st.info(f"📎 File '{uploaded_file.name}' loaded ({len(transcript_content)} characters extracted).")
            except Exception as e:
                st.error(f"Failed to read file: {e}")
        else:
            transcript_content = pasted_text
 
        if st.button("💾 Save & Upload Transcript", type="primary", key="save_transcript_btn"):
            if not transcript_content.strip():
                st.warning("Please upload a file or paste transcript text before saving.")
            else:
                try:
                    db.upload_transcript(project["id"], transcript_content.strip())
                    _cached_get_transcript.clear()
                    st.success("🎉 Transcript saved to Supabase!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Failed to upload transcript: {e}")
 
        st.markdown('</div>', unsafe_allow_html=True)
 
    with col_right:
        st.markdown('<div class="glass-card">', unsafe_allow_html=True)
        st.markdown('<div class="accent-bar"></div>', unsafe_allow_html=True)
        st.markdown("#### 📊 Transcript Preview")
 
        if existing_transcript.strip():
            st.markdown("<span class='status-badge status-completed'>✅ SAVED</span>", unsafe_allow_html=True)
            st.markdown("---")
            preview = existing_transcript[:600] + ("..." if len(existing_transcript) > 600 else "")
            st.text(preview)
        else:
            st.markdown("<span class='status-badge status-pending'>NOT UPLOADED</span>", unsafe_allow_html=True)
            st.info("No transcript saved yet for this project.")
 
        st.markdown('</div>', unsafe_allow_html=True)
 
    # ── Step 2: Task Agent + HITL ──────────────────────────────
    if existing_transcript.strip():
        render_task_agent_section(existing_transcript, project["id"])
    else:
        st.markdown("---")
        st.info("📌 Upload and save a transcript above to enable the Task Agent.")

    # ── Step 3: Planning Agent ─────────────────────────────────
    if st.session_state.approved_requirements:
        render_planning_agent_section()
    elif existing_transcript.strip() and st.session_state.task_output:
        st.markdown("---")
        st.info("📌 Approve the extracted requirements above to enable the Planning Agent.")

    # ── Step 4: Feasibility Agent ─────────────────────────────
    if st.session_state.plan_output:
        render_feasibility_section()
    elif st.session_state.approved_requirements:
        st.markdown("---")
        st.info("📌 Run the Planning Agent above to enable the Feasibility Study.")

    # ── Step 4b: HITL #2 — Approve Plan + Feasibility ─────────
    if st.session_state.plan_output and st.session_state.feasibility_output:
        st.markdown("---")
        st.markdown("### 🧑‍💼 HITL #2: Review Plan & Feasibility")
        st.markdown('<div class="glass-card">', unsafe_allow_html=True)
        st.markdown('<div class="accent-bar-green"></div>', unsafe_allow_html=True)
        st.markdown("Review the Planning and Feasibility outputs before proceeding to Estimation.")

        hitl2_col1, hitl2_col2, hitl2_col3 = st.columns(3)

        with hitl2_col1:
            if st.button("✅ Approve Plan & Feasibility", type="primary", use_container_width=True, key="hitl2_approve_plan_feas_btn"):
                st.session_state.approved_plan = st.session_state.plan_output.model_dump()
                st.session_state.approved_feasibility = st.session_state.feasibility_output.model_dump()
                st.success("Plan and Feasibility approved! Ready for Estimation Agent.")
                st.rerun()

        with hitl2_col2:
            if st.button("🔄 Regenerate Plan", use_container_width=True, key="hitl2_regen_plan_btn"):
                with st.spinner("🏗️ Regenerating plan..."):
                    try:
                        _pid = (st.session_state.selected_project or {}).get("id")
                        result = call_planning_agent(st.session_state.approved_requirements, project_id=_pid)
                        st.session_state.plan_output = result
                        st.session_state.feasibility_output = None
                        st.session_state.approved_plan = None
                        st.session_state.approved_feasibility = None
                        st.session_state.estimation_output = None
                        st.session_state.approved_estimation = None
                        st.session_state.report_output = None
                        st.rerun()
                    except Exception as e:
                        st.error(f"Plan regeneration failed: {e}")

        with hitl2_col3:
            if st.button("🔁 Re-run Feasibility", use_container_width=True, key="hitl2_reerun_feas_btn"):
                with st.spinner("🔍 Re-running feasibility..."):
                    try:
                        result = call_feasibility_agent(
                            st.session_state.approved_requirements,
                            st.session_state.plan_output.model_dump(),
                        )
                        st.session_state.feasibility_output = result
                        st.session_state.approved_plan = None
                        st.session_state.approved_feasibility = None
                        st.session_state.estimation_output = None
                        st.session_state.approved_estimation = None
                        st.session_state.report_output = None
                        st.rerun()
                    except Exception as e:
                        st.error(f"Feasibility re-run failed: {e}")

        if st.session_state.get("approved_feasibility"):
            st.success("🎉 Plan and Feasibility are **approved**! Ready for the Estimation Agent.")

        st.markdown('</div>', unsafe_allow_html=True)
    elif st.session_state.plan_output:
        st.markdown("---")
        st.info("📌 Run the Feasibility Agent above to enable HITL #2 review.")

    # ── Step 5: Estimation Agent ────────────────────────────
    if st.session_state.get("approved_feasibility"):
        render_estimation_section()
    elif st.session_state.plan_output and st.session_state.feasibility_output:
        st.markdown("---")
        st.info("📌 Approve Plan & Feasibility above to enable the Estimation Agent.")

    # ── Step 6: HITL #3 — Approve Estimation ─────────────────
    if st.session_state.estimation_output:
        st.markdown("---")
        st.markdown("### 🧑‍💼 HITL #3: Review Estimation")
        st.markdown('<div class="glass-card">', unsafe_allow_html=True)
        st.markdown('<div class="accent-bar-green"></div>', unsafe_allow_html=True)
        st.markdown("Review the effort estimation before generating the final report.")

        hitl3_col1, hitl3_col2 = st.columns(2)

        with hitl3_col1:
            if st.button("✅ Approve Estimation", type="primary", use_container_width=True, key="hitl3_approve_est_btn"):
                st.session_state.approved_estimation = st.session_state.estimation_output.model_dump()
                st.success("Estimation approved! Ready for Report Agent.")
                st.rerun()

        with hitl3_col2:
            if st.button("📊 Regenerate Estimation", use_container_width=True, key="hitl3_regen_est_btn"):
                with st.spinner("📊 Regenerating estimation..."):
                    try:
                        _pid = (st.session_state.selected_project or {}).get("id")
                        result = call_estimation_agent(
                            st.session_state.approved_requirements,
                            st.session_state.plan_output.model_dump(),
                            st.session_state.feasibility_output.model_dump(),
                            project_id=_pid,
                        )
                        st.session_state.estimation_output = result
                        st.session_state.approved_estimation = None
                        st.session_state.report_output = None
                        st.rerun()
                    except Exception as e:
                        st.error(f"Estimation regeneration failed: {e}")

        if st.session_state.approved_estimation:
            st.success("🎉 Estimation is **approved**! Ready for the Report Agent.")

        st.markdown('</div>', unsafe_allow_html=True)

    # ── Step 7: Report Agent ──────────────────────────────────
    if st.session_state.approved_estimation:
        render_report_section()

# -------------------------------------------------------------
# Page router
# -------------------------------------------------------------
if st.session_state.user is None:
    render_auth_page()
else:
    render_dashboard()
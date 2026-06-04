import sys
from pathlib import Path
 
# Add root folder to sys.path if not present to ensure backend imports work
root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.append(str(root_dir))
 
import streamlit as st
import backend.supabase as db
from backend.agents.task_agent import run_task_agent
 
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
                result = run_task_agent(transcript)
                st.session_state.task_output = result
                st.session_state.approved_requirements = None  # Reset approval on re-run
                st.success("✅ Task Agent completed successfully!")
                st.rerun()
            except Exception as e:
                st.error(f"Task Agent failed: {e}")
 
    # Display results if available
    if st.session_state.task_output:
        output = st.session_state.task_output
 
        st.markdown("#### 📋 Extracted Requirements — Please Review")
 
        tab1, tab2, tab3, tab4 = st.tabs(["🔴 Pain Points", "✅ Requirements", "⚠️ Constraints", "🎯 Business Goals"])
 
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
                st.success("Requirements approved! Ready for the Planning Agent.")
                st.rerun()
 
        with hitl_col2:
            if st.button("🔄 Regenerate", use_container_width=True, key="regen_btn"):
                with st.spinner("🤖 Regenerating..."):
                    try:
                        result = run_task_agent(transcript)
                        st.session_state.task_output = result
                        st.session_state.approved_requirements = None
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
 
            if st.button("💾 Save Edits & Approve", type="primary", key="save_edits_btn"):
                from backend.schemas.task_schema import TaskAgentOutput
                edited_output = TaskAgentOutput(
                    pain_points=[x.strip() for x in edited_pain.split("\n") if x.strip()],
                    requirements=[x.strip() for x in edited_reqs.split("\n") if x.strip()],
                    constraints=[x.strip() for x in edited_cons.split("\n") if x.strip()],
                    business_goals=[x.strip() for x in edited_goals.split("\n") if x.strip()],
                )
                st.session_state.task_output = edited_output
                st.session_state.approved_requirements = edited_output.model_dump()
                st.session_state["hitl_edit_mode"] = False
                st.success("✅ Edits saved and requirements approved!")
                st.rerun()
 
        # Show approved confirmation
        if st.session_state.approved_requirements:
            st.success("🎉 Requirements are **approved** and ready for the Planning Agent in the next phase!")
 
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
        st.rerun()
 
    st.sidebar.markdown("---")
    st.sidebar.markdown("### 📁 Project Management")
 
    try:
        projects = db.get_projects(user.id)
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
 
    chosen_project_name = st.sidebar.selectbox(
        "Select Active Project",
        options=project_options,
        index=selected_index,
        key="project_selector"
    )
 
    if chosen_project_name != "-- Select a Project --":
        selected_project = next(p for p in projects if p["name"] == chosen_project_name)
        if (not st.session_state.selected_project) or (st.session_state.selected_project["id"] != selected_project["id"]):
            st.session_state.selected_project = selected_project
            st.session_state.task_output = None
            st.session_state.approved_requirements = None
            st.rerun()
    else:
        st.session_state.selected_project = None
 
    st.sidebar.markdown("#### Create New Project")
    new_proj_name = st.sidebar.text_input("Project Name", placeholder="e.g. Client X - Core POC", key="new_proj_input")
    if st.sidebar.button("Add Project", type="primary", use_container_width=True, key="add_proj_btn"):
        if not new_proj_name.strip():
            st.sidebar.warning("Please enter a project name.")
        else:
            try:
                new_project = db.create_project(user.id, new_proj_name.strip())
                st.session_state.selected_project = new_project
                st.session_state.task_output = None
                st.session_state.approved_requirements = None
                st.sidebar.success(f"Project '{new_proj_name}' created!")
                st.rerun()
            except Exception as e:
                st.sidebar.error(f"Failed to create project: {e}")
 
    # --- Pipeline status in sidebar ---
    st.sidebar.markdown("---")
    st.sidebar.markdown("### ⚡ Pipeline Status")
    transcript_done = False
    task_done = bool(st.session_state.task_output)
    approved_done = bool(st.session_state.approved_requirements)
 
    if st.session_state.selected_project:
        try:
            rec = db.get_transcript(st.session_state.selected_project["id"])
            transcript_done = bool(rec and rec.get("content", "").strip())
        except Exception:
            pass
 
    st.sidebar.markdown(f"{'✅' if transcript_done else '⬜'} Transcript Upload")
    st.sidebar.markdown(f"{'✅' if task_done else '⬜'} Task Agent")
    st.sidebar.markdown(f"{'✅' if approved_done else '⬜'} HITL Approval")
    st.sidebar.markdown(f"{'⬜'} Planning Agent")
    st.sidebar.markdown(f"{'⬜'} Feasibility Agent")
    st.sidebar.markdown(f"{'⬜'} Report Agent")
 
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
        transcript_record = db.get_transcript(project["id"])
        if transcript_record:
            existing_transcript = transcript_record.get("content", "")
    except Exception as e:
        st.error(f"Error fetching transcript: {e}")
 
    with col_left:
        st.markdown('<div class="glass-card">', unsafe_allow_html=True)
        st.markdown('<div class="accent-bar-purple"></div>', unsafe_allow_html=True)
        st.markdown("#### 📄 Transcript Input")
 
        uploaded_file = st.file_uploader("Upload Meeting Transcript (.txt)", type=["txt"], key="transcript_uploader")
 
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
                transcript_content = uploaded_file.read().decode("utf-8")
                st.info(f"📎 File '{uploaded_file.name}' loaded.")
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
 
# -------------------------------------------------------------
# Page router
# -------------------------------------------------------------
if st.session_state.user is None:
    render_auth_page()
else:
    render_dashboard()
import sys
from pathlib import Path

root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

import asyncio
import io
import re
from datetime import datetime
from functools import partial
from typing import Optional

import chainlit as cl
import pandas as pd

import backend.supabase as db
from backend.api.client import (
    call_task_agent,
    call_planning_agent,
    call_feasibility_agent,
    call_report_agent,
)
from backend.agents.estimation_agent import run_estimation_agent
from backend.rag.retrival import retrieve_context as _retrieve_context, format_context_for_prompt as _format_context
from backend.report_generator import generate_docx, generate_pdf, generate_json, generate_markdown
from backend.rag.ingestion import ingest_document, list_project_documents, extract_text
from backend.rag.retrival import retrieve_context, format_context_for_prompt
from backend.llm_client import generate_with_fallback


# ─────────────────────────────────────────────────────────────────────────────
# Auth
# ─────────────────────────────────────────────────────────────────────────────

@cl.password_auth_callback
async def auth_callback(username: str, password: str) -> Optional[cl.User]:
    """Sign in; auto-provision new accounts on first login."""
    try:
        res = db.sign_in(username, password)
        return cl.User(identifier=res.user.email, metadata={"user_id": res.user.id})
    except Exception:
        pass
    try:
        db.sign_up(username, password)
        res = db.sign_in(username, password)
        return cl.User(identifier=res.user.email, metadata={"user_id": res.user.id})
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Session state
# ─────────────────────────────────────────────────────────────────────────────

def _state() -> dict:
    s = cl.user_session.get("state")
    if s is None:
        s = {
            "step": "project_select",
            "selected_project": None,
            "task_output": None,
            "approved_requirements": None,
            "plan_output": None,
            "feasibility_output": None,
            "approved_plan": None,
            "approved_feasibility": None,
            "estimation_output": None,
            "approved_estimation": None,
            "report_output": None,
            "current_transcript": "",
            "include_mvp": False,
            "_hitl1_feedback": "",
            "_hitl2_feedback": "",
            "_hitl3_feedback": "",
            "_expecting_paste": False,
            "qa_history": [],
        }
        cl.user_session.set("state", s)
    return s


def _save(s: dict) -> None:
    cl.user_session.set("state", s)


def _reset_pipeline(s: dict) -> None:
    for k in ("plan_output", "feasibility_output", "approved_plan",
              "approved_feasibility", "estimation_output", "approved_estimation",
              "report_output"):
        s[k] = None


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _df_to_md(df: pd.DataFrame) -> str:
    try:
        return df.to_markdown(index=False)
    except Exception:
        return df.to_string(index=False)


def _sanitize_mermaid(diagram: str) -> str:
    cleaned = diagram.strip()
    # Strip opening/closing code fence lines only (not content inside)
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        # Drop first line (```mermaid or ```) and last line (```)
        start = 1
        if lines[0].strip().lower() in ("```mermaid", "```"):
            start = 1
        end = len(lines)
        if lines[-1].strip() == "```":
            end = len(lines) - 1
        cleaned = "\n".join(lines[start:end]).strip()
    # Normalize escaped newlines
    cleaned = cleaned.replace("\\n", "\n")
    # Collapse 3+ blank lines
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _build_estimation_df(estimation, include_mvp: bool = False) -> pd.DataFrame:
    struct_cols = estimation.structural_columns or []
    owner_cols  = estimation.owner_columns or []
    rows = []
    for item in estimation.estimations:
        data = item if isinstance(item, dict) else item.model_dump(warnings=False)
        row = {col: data.get(col, "") for col in struct_cols}
        owner_hours = data.get("owner_hours") or {}
        for col in owner_cols:
            row[f"{col} (hrs)"] = owner_hours.get(col, 0)
        row["Tech Remarks"] = data.get("tech_remarks", "")
        row["BA Remarks"]   = ""
        rows.append(row)
    # Totals row
    t_data = estimation.totals if isinstance(estimation.totals, dict) else estimation.totals.model_dump()
    totals_row = {col: "" for col in struct_cols}
    if len(struct_cols) > 1:
        totals_row[struct_cols[1]] = "TOTALS"
    owner_bd = t_data.get("owner_breakdown") or {}
    for col in owner_cols:
        totals_row[f"{col} (hrs)"] = owner_bd.get(col, 0)
    totals_row["Tech Remarks"] = f"Grand Total: {t_data.get('total_hours', 0)} hrs"
    totals_row["BA Remarks"]   = ""
    rows.append(totals_row)
    all_cols = struct_cols + [f"{c} (hrs)" for c in owner_cols] + ["Tech Remarks", "BA Remarks"]
    return pd.DataFrame(rows, columns=all_cols)


def _pipeline_progress(s: dict) -> str:
    steps = [
        ("Project Selected",      bool(s["selected_project"])),
        ("Transcript Uploaded",   bool(s["current_transcript"])),
        ("Task Agent",            bool(s["task_output"])),
        ("Requirements Approved", bool(s["approved_requirements"])),
        ("Planning Agent",        bool(s["plan_output"])),
        ("Feasibility Agent",     bool(s["feasibility_output"])),
        ("Plan & Feas. Approved", bool(s.get("approved_feasibility"))),
        ("Estimation Agent",      bool(s["estimation_output"])),
        ("Estimation Approved",   bool(s["approved_estimation"])),
        ("Final Report",          bool(s["report_output"])),
    ]
    done = sum(1 for _, d in steps if d)
    lines = [f"**Pipeline Progress: {done}/{len(steps)}**\n"]
    for label, d in steps:
        lines.append(f"{'✅' if d else '⬜'} {label}")
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Q&A RAG helpers
# ─────────────────────────────────────────────────────────────────────────────

def _report_to_index_text(report: dict) -> str:
    """Flatten report dict to plain text for RAG indexing."""
    parts = []
    for key in ["executive_summary", "background_summary", "recommendations_next_steps", "architecture_summary"]:
        val = report.get(key, "")
        if val:
            parts.append(f"=== {key.replace('_', ' ').title()} ===\n{val}")
    for key in ["assumptions", "constraints", "business_goals", "technology_context"]:
        items = report.get(key, [])
        if isinstance(items, list) and items:
            lines = "\n".join(f"- {i}" for i in items if isinstance(i, str))
            if lines:
                parts.append(f"=== {key.replace('_', ' ').title()} ===\n{lines}")
    return "\n\n".join(p for p in parts if p.strip())


def _task_output_to_text(output) -> str:
    lines = []
    for label, items in [
        ("Pain Points",     output.pain_points or []),
        ("Requirements",    output.requirements or []),
        ("Constraints",     output.constraints or []),
        ("Business Goals",  output.business_goals or []),
    ]:
        if items:
            lines.append(f"=== {label} ===")
            lines.extend(f"- {i}" for i in items)
            lines.append("")
    tech_ctx = getattr(output, "technology_context", {}) or {}
    if tech_ctx:
        lines.append("=== Technology Context ===")
        for k, v in tech_ctx.items():
            lines.append(f"- {k.replace('_', ' ').title()}: {v}")
    return "\n".join(lines)


def _plan_output_to_text(output) -> str:
    lines = [f"=== Architecture Type ===\n{output.architecture_type}\n"]
    if output.tech_stack:
        lines.append("=== Tech Stack ===")
        for cat, tech in output.tech_stack.items():
            reason = (output.recommendation_reason or {}).get(cat, "")
            suffix = f" — {reason}" if reason else ""
            lines.append(f"- {cat.replace('_', ' ').title()}: {tech}{suffix}")
        lines.append("")
    summary = output.architecture_summary
    if summary:
        lines += [
            "=== Architecture Summary ===",
            f"Overview: {summary.overview}",
            f"Workflow: {summary.workflow}",
            f"Data Flow: {summary.data_flow}",
        ]
    return "\n".join(lines)


def _feasibility_output_to_text(output) -> str:
    lines = [
        "=== Feasibility Assessment ===",
        f"Complexity Level: {output.complexity_level}",
        f"Architecture Confidence: {getattr(output, 'architecture_confidence', '—')}",
        f"Feasibility Confidence: {getattr(output, 'feasibility_confidence', '—')}",
        f"\nSummary: {output.feasibility_summary}",
    ]
    if output.technical_risks:
        lines.append("\n=== Technical Risks ===")
        for risk in output.technical_risks:
            lines += [
                f"Risk: {risk.risk}",
                f"  Impact: {risk.impact}",
                f"  Mitigation: {risk.mitigation}",
            ]
    return "\n".join(lines)


def _estimation_output_to_text(estimation) -> str:
    lines = ["=== Effort Estimation — Work Breakdown Structure ==="]
    struct_cols = estimation.structural_columns or []
    owner_cols  = estimation.owner_columns or []
    for item in estimation.estimations:
        data = item if isinstance(item, dict) else item.model_dump(warnings=False)
        parts = [str(data.get(col, "")) for col in struct_cols if data.get(col)]
        owner_hours = data.get("owner_hours") or {}
        for col in owner_cols:
            hrs = owner_hours.get(col, 0)
            if hrs:
                parts.append(f"{col}: {hrs} hrs")
        remarks = data.get("tech_remarks", "")
        if remarks:
            parts.append(f"Notes: {remarks}")
        lines.append("- " + " | ".join(p for p in parts if p))
    t_data = estimation.totals if isinstance(estimation.totals, dict) else estimation.totals.model_dump()
    lines.append(f"\n=== Totals ===\nGrand Total: {t_data.get('total_hours', 0)} hrs")
    for owner, hrs in (t_data.get("owner_breakdown") or {}).items():
        lines.append(f"  {owner}: {hrs} hrs")
    return "\n".join(lines)


async def _ingest_to_rag(project_id: str, text: str, doc_name: str, doc_type: str = "txt") -> None:
    """Silently embed and store text in Supabase for Q&A retrieval."""
    try:
        content = text.encode("utf-8")
        res = await asyncio.to_thread(partial(ingest_document, project_id, content, doc_name, doc_type))
        if res.get("success"):
            print(f"[RAG] Indexed {doc_name}: {res['chunks_inserted']} chunks")
        else:
            print(f"[RAG] Index failed for {doc_name}: {res.get('error')}")
    except Exception as e:
        print(f"[RAG] ingest error for {doc_name}: {e}")


_QA_HISTORY_LIMIT = 6  # keep last 6 turns (3 Q&A pairs) in the prompt

async def _qa_answer(s: dict, question: str) -> None:
    """Retrieve context from Supabase and answer a Q&A question with conversation history."""
    project_id = (s["selected_project"] or {}).get("id", "")
    proj_name  = (s["selected_project"] or {}).get("name", "this project")

    if not project_id:
        await cl.Message(content="❌ No project selected — cannot search project documents.").send()
        return

    # Detect language and translate query to English for retrieval
    lang_prompt = f"""Detect the language of this text and if it is not English, translate it to English.
Return a JSON object with two keys: "language" (the detected language name in English, e.g. "Hindi", "English", "Spanish") and "english_query" (the English translation, or the original if already English).
Text: {question}
Return only valid JSON, no markdown."""
    try:
        lang_raw = await asyncio.to_thread(partial(generate_with_fallback, lang_prompt, agent_name="lang_detect"))
        import json as _json
        lang_data = _json.loads(lang_raw.strip().strip("```json").strip("```").strip())
        detected_language = lang_data.get("language", "English")
        search_query = lang_data.get("english_query", question)
    except Exception:
        detected_language = "English"
        search_query = question

    # Generate multiple search angles to handle paraphrased/conceptually similar questions
    expand_prompt = f"""Generate 3 different search queries to retrieve relevant information for this question from a software project document.
Each query should approach the topic from a different angle (direct, conceptual, keyword-focused).
Return only a JSON array of 3 strings. No explanation, no markdown.
Question: {search_query}"""
    try:
        expand_raw = await asyncio.to_thread(partial(generate_with_fallback, expand_prompt, agent_name="query_expander"))
        import json as _json2
        extra_queries = _json2.loads(expand_raw.strip().strip("```json").strip("```").strip())
        if not isinstance(extra_queries, list):
            extra_queries = []
    except Exception:
        extra_queries = []
    all_queries = [search_query] + extra_queries[:2]  # original + 2 extras

    # Retrieve relevant chunks using all query angles, deduplicate by chunk id
    async with cl.Step(name="Searching Documents", type="retrieval") as step:
        step.input = search_query
        try:
            seen_ids: set = set()
            merged_chunks: list = []
            for q in all_queries:
                results = await asyncio.to_thread(partial(retrieve_context, project_id, q, 6))
                for c in results:
                    cid = c.get("id") or c.get("chunk_text", "")[:80]
                    if cid not in seen_ids:
                        seen_ids.add(cid)
                        merged_chunks.append(c)
            # Sort by similarity descending (best first), keep top 10
            merged_chunks.sort(key=lambda x: x.get("similarity", 0), reverse=True)
            chunks = merged_chunks[:10]
            context = format_context_for_prompt(chunks)
            step.output = f"Found {len(chunks)} unique chunk(s) across {len(all_queries)} search angles"
        except Exception as e:
            chunks = []
            context = ""
            step.output = f"Retrieval failed: {e}"

    # Build conversation history block (last N turns)
    history = s.get("qa_history") or []
    history_block = ""
    if history:
        lines = ["[CONVERSATION HISTORY]"]
        for turn in history[-_QA_HISTORY_LIMIT:]:
            lines.append(f"User: {turn['q']}")
            lines.append(f"Assistant: {turn['a']}")
        lines.append("[END OF HISTORY]")
        history_block = "\n".join(lines)

    lang_instruction = (
        f"IMPORTANT: The user asked in {detected_language}. You MUST respond in {detected_language}."
        if detected_language.lower() != "english"
        else ""
    )

    prompt = f"""You are an AI assistant answering questions about a software project analysis for "{proj_name}".
{lang_instruction}

{context if context else "(No indexed documents found — answer from general knowledge.)"}

{history_block}

Current question: {question}

Answer concisely and accurately, taking the conversation history into account for any follow-up references. Reference specific sections from the documents when possible. If the answer is not in the documents, say so clearly. {lang_instruction}"""

    async with cl.Step(name="Generating Answer", type="llm") as step:
        step.input = question
        try:
            answer = await asyncio.to_thread(partial(generate_with_fallback, prompt, agent_name="qa_agent"))
            step.output = answer[:200] + ("…" if len(answer) > 200 else "")
        except Exception as e:
            answer = f"❌ Failed to generate answer: {e}"
            step.output = str(e)

    # Persist this turn to history
    history.append({"q": question, "a": answer})
    s["qa_history"] = history
    _save(s)

    await cl.Message(content=answer).send()


# ─────────────────────────────────────────────────────────────────────────────
# Step display functions (mirrors each render_* in app.py)
# ─────────────────────────────────────────────────────────────────────────────

async def _show_project_menu(user: cl.User, s: dict) -> None:
    s["step"] = "project_select"
    _save(s)
    try:
        projects = db.get_projects(user.metadata["user_id"])
    except Exception as e:
        await cl.Message(content=f"❌ Could not load projects: {e}").send()
        projects = []

    if projects:
        actions = [
            cl.Action(name="select_project", payload={"id": p["id"], "name": p["name"]}, label=p["name"])
            for p in projects[:8]
        ]
        actions.append(cl.Action(name="new_project", payload={}, label="➕ Create New Project"))
        await cl.Message(content="📁 **Select a project** or create a new one:", actions=actions).send()
    else:
        await cl.Message(content="No projects yet. Type a project name to create your first one:").send()
        s["step"] = "create_project"
        _save(s)


async def _show_transcript_step(project: dict, s: dict) -> None:
    s["step"] = "transcript"
    _save(s)
    try:
        tr = db.get_transcript(project["id"])
        if tr and tr.get("content", "").strip():
            s["current_transcript"] = tr["content"]
            _save(s)
            preview = tr["content"][:400] + ("..." if len(tr["content"]) > 400 else "")
            await cl.Message(
                content=(
                    f"📄 **Existing transcript** for *{project['name']}*:\n\n"
                    f"```\n{preview}\n```\n\nUse this or provide a new one?"
                ),
                actions=[
                    cl.Action(name="use_existing_transcript", payload={}, label="✅ Use Existing"),
                    cl.Action(name="upload_new_transcript",   payload={}, label="📤 Upload New File"),
                    cl.Action(name="paste_new_transcript",    payload={}, label="📝 Paste New Text"),
                ],
            ).send()
            return
    except Exception:
        pass

    await cl.Message(
        content=f"### Step 1 — Upload Transcript for *{project['name']}*\n\nHow would you like to provide the client meeting transcript?",
        actions=[
            cl.Action(name="upload_new_transcript", payload={}, label="📤 Upload File (PDF/DOCX/TXT)"),
            cl.Action(name="paste_new_transcript",  payload={}, label="📝 Paste Text"),
        ],
    ).send()


# ── Step 2: Task Agent ────────────────────────────────────────────────────────

async def _show_task_agent_step(s: dict) -> None:
    s["step"] = "task_agent"
    _save(s)
    await cl.Message(
        content=(
            "### Step 2 — Task Identification Agent\n\n"
            "Extracts **requirements**, **pain points**, **constraints**, **business goals**, "
            "and **technology context** from your transcript using Gemini AI.\n\n"
            "*(Optional: upload reference PDFs/docs to give agents extra context)*"
        ),
        actions=[
            cl.Action(name="run_task_agent",  payload={}, label="▶ Run Task Agent"),
            cl.Action(name="upload_ref_docs", payload={}, label="📄 Upload Reference Docs"),
        ],
    ).send()


async def _show_hitl1(s: dict) -> None:
    """HITL #1 — mirrors render_task_agent_section results + review block."""
    s["step"] = "hitl1"
    _save(s)
    output = s["task_output"]

    lines = ["### 📋 Extracted Requirements — Please Review\n"]

    pain_points = output.pain_points or []
    if pain_points:
        lines.append("**🔴 Pain Points:**")
        for p in pain_points:
            lines.append(f"- {p}")
        lines.append("")

    requirements = output.requirements or []
    if requirements:
        lines.append("**✅ Requirements:**")
        for r in requirements:
            lines.append(f"- {r}")
        lines.append("")

    constraints = output.constraints or []
    if constraints:
        lines.append("**⚠️ Constraints:**")
        for c in constraints:
            lines.append(f"- {c}")
        lines.append("")

    goals = output.business_goals or []
    if goals:
        lines.append("**🎯 Business Goals:**")
        for g in goals:
            lines.append(f"- {g}")
        lines.append("")

    tech_ctx = getattr(output, "technology_context", {}) or {}
    if tech_ctx:
        lines.append("**💻 Technology Context:**")
        for k, v in tech_ctx.items():
            lines.append(f"- **{k.replace('_', ' ').title()}:** {v}")
        lines.append("")

    lines.append("---")
    lines.append("#### 🧑‍💼 Human-in-the-Loop Review")
    lines.append("Click **✅ Approve** to continue, or **🔄 Regenerate** — which will ask what to change before re-running.")

    await cl.Message(
        content="\n".join(lines),
        actions=[
            cl.Action(name="hitl1_approve", payload={}, label="✅ Approve & Auto-Run"),
            cl.Action(name="hitl1_regen",   payload={}, label="🔄 Regenerate"),
        ],
    ).send()


# ── Step 3: Planning Agent ────────────────────────────────────────────────────

async def _show_planning_result(s: dict) -> None:
    """Mirrors render_planning_agent_section."""
    plan = s["plan_output"]
    lines = [
        "### 🏗️ Planning Agent — Architecture\n",
        f"**Architecture Type:** {plan.architecture_type}\n",
    ]

    if plan.tech_stack:
        lines.append("**🛠️ Tech Stack:**")
        for cat, tech in plan.tech_stack.items():
            reason = (plan.recommendation_reason or {}).get(cat, "")
            label = cat.replace("_", " ").title()
            suffix = f"\n  > *{reason}*" if reason else ""
            lines.append(f"- **{label}:** {tech}{suffix}")
        lines.append("")

    summary = plan.architecture_summary
    lines += [
        "**📐 Architecture Summary:**",
        f"- **Overview:** {summary.overview}",
        f"- **Workflow:** {summary.workflow}",
        f"- **Data Flow:** {summary.data_flow}",
        "",
    ]

    if plan.reference_docs:
        lines.append("**📚 Reference Docs:**")
        for doc in plan.reference_docs:
            lines.append(f"- [{doc.title}]({doc.url})")
        lines.append("")

    await cl.Message(content="\n".join(lines)).send()

    # Show architecture diagram — Excalidraw PNG preferred, mermaid fallback
    excalidraw_data = getattr(plan, "excalidraw_diagram", None) or {}
    if excalidraw_data.get("nodes"):
        try:
            from backend.excalidraw_utils import build_excalidraw_json, excalidraw_to_png
            scene = build_excalidraw_json(excalidraw_data)
            png_bytes = await asyncio.to_thread(excalidraw_to_png, scene)
            if png_bytes:
                img = cl.Image(name="architecture.png", content=png_bytes, display="inline")
                await cl.Message(content="**🗺️ Architecture Diagram:**", elements=[img]).send()
        except Exception as _exc:
            print(f"[Chainlit] Excalidraw render failed: {_exc}")
    elif plan.mermaid_diagram:
        diagram = _sanitize_mermaid(plan.mermaid_diagram)
        await cl.Message(content=f"**🗺️ Architecture Diagram:**\n\n```mermaid\n{diagram}\n```").send()


# ── Step 4: Feasibility Agent ─────────────────────────────────────────────────

async def _show_feasibility_result(s: dict) -> None:
    """Mirrors render_feasibility_section."""
    feas = s["feasibility_output"]
    lines = ["### 🔍 Feasibility Assessment\n"]

    complexity = feas.complexity_level or "Unknown"
    arch_conf  = getattr(feas, "architecture_confidence", None) or "—"
    feas_conf  = getattr(feas, "feasibility_confidence", None) or "—"

    lines += [
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Complexity | {complexity} |",
        f"| Architecture Confidence | {arch_conf} |",
        f"| Feasibility Confidence | {feas_conf} |",
        "",
        f"**Summary:** {feas.feasibility_summary}\n",
    ]

    if feas.technical_risks:
        lines.append("**⚠️ Technical Risks:**")
        for risk in feas.technical_risks:
            lines.append(f"\n**{risk.risk}**")
            lines.append(f"- Impact: {risk.impact}")
            lines.append(f"- Mitigation: {risk.mitigation}")
        lines.append("")

    await cl.Message(content="\n".join(lines)).send()


# ── Step 4b: HITL #2 ─────────────────────────────────────────────────────────

async def _show_hitl2(s: dict) -> None:
    """Mirrors inline HITL #2 block in render_dashboard (Step 4b)."""
    s["step"] = "hitl2"
    _save(s)

    plan  = s["plan_output"]
    feas  = s["feasibility_output"]

    summary_lines = [
        "### HITL #2 — Review Plan & Feasibility\n",
        f"**Architecture:** {plan.architecture_type}",
    ]
    if plan.tech_stack:
        stack_str = ", ".join(f"{k.replace('_',' ').title()}: {v}" for k, v in list(plan.tech_stack.items())[:4])
        summary_lines.append(f"**Stack:** {stack_str}")
    summary_lines += [
        f"**Complexity:** {feas.complexity_level}  |  "
        f"Arch Confidence: {getattr(feas,'architecture_confidence','—')}  |  "
        f"Feas Confidence: {getattr(feas,'feasibility_confidence','—')}",
        "",
        "Click **✅ Approve** to move to Estimation, or click a **Regenerate** button — it will ask what to change.",
    ]

    await cl.Message(
        content="\n".join(summary_lines),
        actions=[
            cl.Action(name="hitl2_approve",    payload={}, label="✅ Approve Plan & Feasibility"),
            cl.Action(name="hitl2_regen_plan",  payload={}, label="🔄 Regenerate Plan"),
            cl.Action(name="hitl2_rerun_feas",  payload={}, label="🔁 Re-run Feasibility"),
        ],
    ).send()


# ── Step 5: Estimation Agent ──────────────────────────────────────────────────

async def _show_estimation_step(s: dict) -> None:
    """Mirrors render_estimation_section header."""
    s["step"] = "estimation"
    _save(s)
    mvp_label = "ON ✓" if s["include_mvp"] else "OFF"
    await cl.Message(
        content=(
            f"### Step 5 — Effort Estimation\n\n"
            "Generates a **Work Breakdown Structure** with per-module, per-role hour estimates.\n\n"
            f"MVP / Full Build phase split: **{mvp_label}**"
        ),
        actions=[
            cl.Action(name="run_estimation", payload={}, label="▶ Run Estimation Agent"),
            cl.Action(name="toggle_mvp",     payload={}, label="🔀 Toggle MVP Phase Split"),
        ],
    ).send()


async def _show_estimation_result(s: dict) -> None:
    """Mirrors render_estimation_section results block."""
    est     = s["estimation_output"]
    inc_mvp = s["include_mvp"]
    df      = _build_estimation_df(est, include_mvp=inc_mvp)

    t_data = est.totals if isinstance(est.totals, dict) else est.totals.model_dump()
    lines = ["### 📋 Effort Estimation Table\n", _df_to_md(df), ""]
    lines.append(f"**Grand Total: {t_data.get('total_hours', 0)} hrs**")
    owner_bd = t_data.get("owner_breakdown") or {}
    if owner_bd:
        breakdown = " | ".join(f"**{owner}:** {hrs} hrs" for owner, hrs in owner_bd.items())
        lines.append(breakdown)

    await cl.Message(content="\n".join(lines)).send()

    # Excel download via in-memory bytes
    try:
        xl_buf = io.BytesIO()
        with pd.ExcelWriter(xl_buf, engine="openpyxl") as writer:
            df.to_excel(writer, index=False, sheet_name="Effort Estimation")
        await cl.Message(
            content="📥 Download estimation:",
            elements=[cl.File(
                name="effort_estimation.xlsx",
                content=xl_buf.getvalue(),
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                display="inline",
            )],
        ).send()
    except Exception as e:
        await cl.Message(content=f"⚠️ Excel export error: {e}").send()


# ── Step 6: HITL #3 ──────────────────────────────────────────────────────────

async def _show_hitl3(s: dict) -> None:
    """Mirrors inline HITL #3 block in render_dashboard (Step 6)."""
    s["step"] = "hitl3"
    _save(s)
    await cl.Message(
        content=(
            "### HITL #3 — Review Estimation\n\n"
            "Review the effort estimation table above.\n\n"
            "Click **✅ Approve** to proceed to Report, or **📊 Regenerate** — it will ask what to change first."
        ),
        actions=[
            cl.Action(name="hitl3_approve", payload={}, label="✅ Approve Estimation"),
            cl.Action(name="hitl3_regen",   payload={}, label="📊 Regenerate Estimation"),
        ],
    ).send()


# ── Step 7: Report ────────────────────────────────────────────────────────────

async def _show_report_step(s: dict) -> None:
    s["step"] = "report"
    _save(s)
    await cl.Message(
        content=(
            "### Step 7 — Final Report\n\n"
            "Generates a **12-section professional consulting report** suitable for "
            "client, business, and technical review."
        ),
        actions=[cl.Action(name="generate_report", payload={}, label="▶ Generate Final Report")],
    ).send()


async def _show_report_result(s: dict) -> None:
    """Mirrors render_report_section — all 11 sections."""
    report    = s["report_output"]
    proj_name = (s["selected_project"] or {}).get("name", "Project")

    # ── Cover ─────────────────────────────────────────────────────────────────
    await cl.Message(content=(
        f"## 📋 {proj_name} — Consulting Report\n"
        f"*{datetime.now().strftime('%B %d, %Y')} · AI-Generated POC Analysis · 11-Section Report*"
    )).send()

    # ── 01. Executive Summary ─────────────────────────────────────────────────
    await cl.Message(content=(
        "### 01. Executive Summary\n\n" + report.get("executive_summary", "")
    )).send()

    # ── 02. Background Summary ────────────────────────────────────────────────
    await cl.Message(content=(
        "### 02. Background Summary\n\n" + report.get("background_summary", "")
    )).send()

    # ── 03. Problem / Need Analysis ───────────────────────────────────────────
    pna = report.get("problem_need_analysis", [])
    if pna:
        df_pna = pd.DataFrame([
            {"Problem / Need": r.get("problem_need", ""), "Business Impact": r.get("business_impact", "")}
            for r in pna
        ])
        await cl.Message(content=f"### 03. Problem / Need Analysis\n\n{_df_to_md(df_pna)}").send()

    # ── 04. Requirements Analysis ─────────────────────────────────────────────
    r04 = ["### 04. Requirements Analysis\n"]

    fr = report.get("functional_requirements", [])
    if fr:
        df_fr = pd.DataFrame([{"ID": r.get("id",""), "Requirement": r.get("requirement","")} for r in fr])
        r04.append("**Functional Requirements:**\n" + _df_to_md(df_fr) + "\n")

    nfr = report.get("non_functional_requirements", [])
    if nfr:
        df_nfr = pd.DataFrame([{"Category": r.get("category",""), "Requirement": r.get("requirement","")} for r in nfr])
        r04.append("**Non-Functional Requirements:**\n" + _df_to_md(df_nfr) + "\n")

    constraints = report.get("constraints", [])
    if constraints:
        r04.append("**Constraints:**")
        r04.extend(f"- {c}" for c in constraints)
        r04.append("")

    goals = report.get("business_goals", [])
    if goals:
        r04.append("**Business Goals:**")
        r04.extend(f"- {g}" for g in goals)
        r04.append("")

    tech_ctx = report.get("technology_context", [])
    if tech_ctx:
        r04.append("**Technology Context:**")
        r04.extend(f"- {t}" for t in tech_ctx)

    await cl.Message(content="\n".join(r04)).send()

    # ── 05. Assumptions ───────────────────────────────────────────────────────
    assumptions = report.get("assumptions", [])
    if assumptions:
        lines_05 = ["### 05. Assumptions\n"]
        lines_05.extend(f"- {a}" for a in assumptions)
        await cl.Message(content="\n".join(lines_05)).send()

    # ── 06. Feature & Module Breakdown ────────────────────────────────────────
    fmb = report.get("feature_module_breakdown", [])
    if fmb:
        df_fmb = pd.DataFrame([
            {"Module": r.get("module",""),
             "Feature / Functionality": r.get("feature_functionality",""),
             "Technologies Used": r.get("technologies_used","")}
            for r in fmb
        ])
        await cl.Message(content=f"### 06. Feature & Module Breakdown\n\n{_df_to_md(df_fmb)}").send()

    # ── 07. Solution Architecture ─────────────────────────────────────────────
    plan_out = s.get("plan_output")
    raw      = report.get("raw_data", {})

    # Resolve excalidraw_diagram from session plan_output or raw report data
    excalidraw_data = {}
    if plan_out and getattr(plan_out, "excalidraw_diagram", None):
        excalidraw_data = plan_out.excalidraw_diagram or {}
    if not excalidraw_data.get("nodes"):
        excalidraw_data = (raw.get("plan") or {}).get("excalidraw_diagram", {}) or {}

    arch_sent = False
    if excalidraw_data.get("nodes"):
        try:
            from backend.excalidraw_utils import build_excalidraw_json, excalidraw_to_png
            scene = build_excalidraw_json(excalidraw_data)
            png_bytes = await asyncio.to_thread(excalidraw_to_png, scene)
            if png_bytes:
                img = cl.Image(name="architecture.png", content=png_bytes, display="inline")
                await cl.Message(content="### 07. Solution Architecture", elements=[img]).send()
                arch_sent = True
        except Exception as _exc:
            print(f"[Chainlit] Report excalidraw render failed: {_exc}")

    if not arch_sent:
        # Mermaid fallback
        mermaid = ""
        if plan_out and getattr(plan_out, "mermaid_diagram", None):
            mermaid = plan_out.mermaid_diagram
        else:
            mermaid = (raw.get("plan") or {}).get("mermaid_diagram", "")
        if mermaid:
            diagram = _sanitize_mermaid(mermaid)
            await cl.Message(
                content=f"### 07. Solution Architecture\n\n```mermaid\n{diagram}\n```"
            ).send()

    # ── 08. Feasibility Assessment ────────────────────────────────────────────
    ft = report.get("feasibility_table", [])
    if ft:
        df_ft = pd.DataFrame([
            {"Metric": r.get("metric",""), "Value": r.get("value",""), "Reason": r.get("reason","")}
            for r in ft
        ])
        await cl.Message(content=f"### 08. Feasibility Assessment\n\n{_df_to_md(df_ft)}").send()

    # ── 09. Risk Assessment ───────────────────────────────────────────────────
    ra = report.get("risk_assessment", [])
    if ra:
        df_ra = pd.DataFrame([
            {"Risk": r.get("risk",""), "Impact": r.get("impact",""),
             "Mitigation Strategy": r.get("mitigation_strategy","")}
            for r in ra
        ])
        await cl.Message(content=f"### 09. Risk Assessment\n\n{_df_to_md(df_ra)}").send()

    # ── 10. Recommendations & Next Steps ─────────────────────────────────────
    await cl.Message(content=(
        "### 10. Recommendations & Next Steps\n\n"
        + report.get("recommendations_next_steps", "")
    )).send()

    # ── 11. Architecture Summary ──────────────────────────────────────────────
    await cl.Message(content=(
        "### 11. Architecture Summary\n\n" + report.get("architecture_summary", "")
    )).send()

    # ── Effort Estimation embedded in report ──────────────────────────────────
    est_obj = s.get("estimation_output")
    if est_obj:
        _inc_mvp = s.get("include_mvp", False)
        df_est   = _build_estimation_df(est_obj, include_mvp=_inc_mvp)
        t_total  = est_obj.totals.total_hours
        try:
            _xl_buf = io.BytesIO()
            with pd.ExcelWriter(_xl_buf, engine="openpyxl") as w:
                df_est.to_excel(w, index=False, sheet_name="Effort Estimation")
            await cl.Message(
                content=f"**📊 Effort Estimation (Grand Total: {t_total} hrs)**\n\n{_df_to_md(df_est)}",
                elements=[cl.File(
                    name="effort_estimation.xlsx",
                    content=_xl_buf.getvalue(),
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    display="inline",
                )],
            ).send()
        except Exception:
            await cl.Message(
                content=f"**📊 Effort Estimation (Grand Total: {t_total} hrs)**\n\n{_df_to_md(df_est)}"
            ).send()

    # ── Downloads ─────────────────────────────────────────────────────────────
    await cl.Message(content="⏳ Preparing download files…").send()
    dl_elements = []
    for label, gen_fn, fname, mime in [
        ("DOCX",     generate_docx,     "project_report.docx",
         "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
        ("PDF",      generate_pdf,      "project_report.pdf",  "application/pdf"),
        ("JSON",     generate_json,     "project_report.json", "application/json"),
        ("Markdown", generate_markdown, "project_report.md",   "text/markdown"),
    ]:
        try:
            buf = await asyncio.to_thread(gen_fn, report)
            data = buf.read()
            if not data:
                raise ValueError("generator returned empty bytes")
            dl_elements.append(
                cl.File(name=fname, content=data, mime=mime, display="inline")
            )
        except Exception as e:
            await cl.Message(content=f"⚠️ {label} generation failed: {e}").send()

    if dl_elements:
        await cl.Message(content="### 📥 Download Report", elements=dl_elements).send()
    else:
        # Fallback: raw JSON always works
        import json as _json
        raw_bytes = _json.dumps(report, indent=2).encode("utf-8")
        await cl.Message(
            content="### 📥 Download Report (JSON fallback — other formats failed)",
            elements=[cl.File(name="project_report.json", content=raw_bytes,
                              mime="application/json", display="inline")],
        ).send()

    # Index transcript + report for Q&A (background — non-blocking)
    project_id = (s["selected_project"] or {}).get("id", "")
    if project_id:
        transcript = s.get("current_transcript", "")
        if transcript.strip():
            asyncio.create_task(_ingest_to_rag(project_id, transcript, "transcript.txt", "txt"))
        report_text = _report_to_index_text(report)
        if report_text.strip():
            asyncio.create_task(_ingest_to_rag(project_id, report_text, "final_report.txt", "txt"))

    s["step"] = "qa_mode"
    _save(s)
    await cl.Message(
        content=(
            "🎉 **Pipeline Complete!**\n\n"
            + _pipeline_progress(s)
            + "\n\n---\n\n"
            "### 💬 Q&A Mode Active\n"
            "The transcript and report are being indexed. Once ready, just **type any question** "
            "about this project below — I'll search the report, transcript, and any uploaded "
            "reference docs to answer.\n\n"
            "*(Indexing runs in the background — ask away in ~10–20 seconds)*"
        ),
        actions=[
            cl.Action(name="download_docx",   payload={}, label="📄 Download Report (DOCX)"),
            cl.Action(name="upload_ref_docs", payload={}, label="📎 Upload More Reference Docs"),
            cl.Action(name="new_project",     payload={}, label="➕ Start New Project"),
        ],
    ).send()


# ─────────────────────────────────────────────────────────────────────────────
# Chat start
# ─────────────────────────────────────────────────────────────────────────────

@cl.on_chat_start
async def on_chat_start():
    user = cl.user_session.get("user")
    s = _state()
    await cl.Message(content=(
        "## ⚡ AI-Powered POC Generator\n\n"
        f"Logged in as **{user.identifier}**\n\n"
        "---\n"
        "This is a **button-driven wizard** — every step is controlled by the action buttons below each message.\n\n"
        "| Step | Action |\n"
        "|------|--------|\n"
        "| 1 | Select / create a project |\n"
        "| 2 | Upload the client transcript |\n"
        "| 3 | Run Task Agent → review & approve |\n"
        "| 4 | Auto-run Planning + Feasibility → review |\n"
        "| 5 | Run Estimation Agent → review & approve |\n"
        "| 6 | Generate Final Report + downloads |\n\n"
        "The **only** time you need to type is: project name, transcript paste, and HITL feedback when clicking **Regenerate**."
    )).send()
    await _show_project_menu(user, s)


# ─────────────────────────────────────────────────────────────────────────────
# Message router
# ─────────────────────────────────────────────────────────────────────────────

_BUTTON_HINT = (
    "👆 **Use the buttons above** to continue the pipeline.\n\n"
    "The text box is only active when: entering a project name, pasting a transcript, "
    "providing **Regenerate** feedback, or typing questions in **Q&A Mode** after the report is complete."
)


@cl.on_message
async def on_message(message: cl.Message):
    user = cl.user_session.get("user")
    s    = _state()
    text = message.content.strip()
    step = s.get("step", "project_select")

    # ── Q&A mode — free-text questions after report is complete ──────────────
    if step == "qa_mode":
        if text:
            await _qa_answer(s, text)
        else:
            await cl.Message(content="💬 Type a question about the project report below.").send()
        return

    # ── Only two pipeline steps accept free text ──────────────────────────────

    # 1. Project name entry
    if step in ("project_select", "create_project"):
        if text:
            await _create_project(user, s, text)
        return

    # 2. Transcript paste (only when the Paste button was clicked first)
    if step == "transcript":
        if s.get("_expecting_paste") and text:
            s["_expecting_paste"] = False
            _save(s)
            await _save_transcript_text(s, text)
        elif message.elements:
            for el in message.elements:
                if getattr(el, "path", None) or getattr(el, "content", None):
                    await _process_transcript_file(s, el)
                    return
        else:
            await cl.Message(content=_BUTTON_HINT).send()
        return

    # ── /restart shortcut (convenience — no other slash commands exposed) ─────
    if text.lower() == "/restart":
        s["step"] = "project_select"
        s["task_output"] = None
        s["approved_requirements"] = None
        _reset_pipeline(s)
        _save(s)
        await _show_project_menu(user, s)
        return

    # ── Everything else: redirect to buttons ─────────────────────────────────
    await cl.Message(content=_BUTTON_HINT).send()


# ─────────────────────────────────────────────────────────────────────────────
# Helper coroutines
# ─────────────────────────────────────────────────────────────────────────────

async def _create_project(user: cl.User, s: dict, name: str) -> None:
    name = name.strip()
    if not name or name.startswith("/"):
        await cl.Message(content="Type a project name to create one (or `/projects` to pick an existing one).").send()
        return
    try:
        proj = db.create_project(user.metadata["user_id"], name)
        s["selected_project"] = proj
        s["task_output"] = None
        s["approved_requirements"] = None
        _reset_pipeline(s)
        _save(s)
        await cl.Message(content=f"✅ Project **{name}** created!").send()
        await _show_transcript_step(proj, s)
    except Exception as e:
        await cl.Message(content=f"❌ Failed to create project: {e}").send()


async def _save_transcript_text(s: dict, text: str) -> None:
    if not text.strip():
        await cl.Message(content="Transcript is empty — please paste actual content.").send()
        return
    project = s["selected_project"]
    try:
        await asyncio.to_thread(db.upload_transcript, project["id"], text.strip())
        s["current_transcript"] = text.strip()
        s["task_output"] = None
        s["approved_requirements"] = None
        _reset_pipeline(s)
        _save(s)
        await cl.Message(content=f"✅ Transcript saved ({len(text):,} chars). Indexing for Q&A in background…").send()
        asyncio.create_task(_ingest_to_rag(project["id"], text.strip(), "transcript.txt", "txt"))
        await _show_task_agent_step(s)
    except Exception as e:
        await cl.Message(content=f"❌ Failed to save transcript: {e}").send()


async def _process_transcript_file(s: dict, file_el) -> None:
    try:
        path = getattr(file_el, "path", None)
        raw  = getattr(file_el, "content", None)
        if path:
            with open(path, "rb") as f:
                content = f.read()
        elif raw:
            content = raw if isinstance(raw, bytes) else raw.encode()
        else:
            await cl.Message(content="❌ Could not read file.").send()
            return
        name = getattr(file_el, "name", "file.txt")
        ext  = name.rsplit(".", 1)[-1].lower() if "." in name else "txt"
        text = await asyncio.to_thread(extract_text, content, ext)
        await _save_transcript_text(s, text)
    except Exception as e:
        await cl.Message(content=f"❌ Failed to process file: {e}").send()


async def _handle_rag_upload(s: dict) -> None:
    project = s["selected_project"]
    try:
        existing = list_project_documents(project["id"])
        if existing:
            doc_list = "\n".join(f"- 📄 {d['document_name']}" for d in existing)
            await cl.Message(content=f"**Indexed documents for *{project['name']}*:**\n{doc_list}").send()
        else:
            await cl.Message(content=f"No documents indexed yet for *{project['name']}*.").send()
    except Exception:
        pass

    files = await cl.AskFileMessage(
        content="📤 Upload reference documents (PDF, DOCX, or TXT) to enrich AI context:",
        accept=["*/*"],
        max_files=5,
        timeout=120,
    ).send()

    if not files:
        await cl.Message(content="No files uploaded.").send()
        return

    for f in files:
        try:
            path = getattr(f, "path", None)
            content = open(path, "rb").read() if path else (
                f.content if isinstance(f.content, bytes) else f.content.encode()
            )
            ext = f.name.rsplit(".", 1)[-1].lower() if "." in f.name else "txt"
            res = await asyncio.to_thread(partial(ingest_document, project["id"], content, f.name, ext))
            if res["success"]:
                await cl.Message(content=f"✅ {f.name}: {res['chunks_inserted']} chunks indexed").send()
            else:
                await cl.Message(content=f"❌ {f.name}: {res.get('error', 'failed')}").send()
        except Exception as e:
            await cl.Message(content=f"❌ {f.name}: {e}").send()


# ─────────────────────────────────────────────────────────────────────────────
# Action callbacks
# ─────────────────────────────────────────────────────────────────────────────

@cl.action_callback("select_project")
async def on_select_project(action: cl.Action):
    user    = cl.user_session.get("user")
    s       = _state()
    proj_id = action.payload.get("id")
    try:
        projects = db.get_projects(user.metadata["user_id"])
        project  = next((p for p in projects if p["id"] == proj_id), None)
        if project:
            s["selected_project"] = project
            s["task_output"] = None
            s["approved_requirements"] = None
            _reset_pipeline(s)
            _save(s)
            await cl.Message(content=f"✅ Project **{project['name']}** selected.").send()
            await _show_transcript_step(project, s)
    except Exception as e:
        await cl.Message(content=f"❌ Error: {e}").send()


@cl.action_callback("new_project")
async def on_new_project(action: cl.Action):
    s = _state()
    s["step"] = "create_project"
    _save(s)
    await cl.Message(content="📝 Type a name for your new project:").send()


@cl.action_callback("use_existing_transcript")
async def on_use_existing_transcript(action: cl.Action):
    s = _state()
    await cl.Message(content="✅ Using existing transcript.").send()
    await _show_task_agent_step(s)


@cl.action_callback("upload_new_transcript")
async def on_upload_new_transcript(action: cl.Action):
    s = _state()
    files = await cl.AskFileMessage(
        content="📤 Upload your transcript (PDF, DOCX, or TXT):",
        accept=["*/*"],
        max_files=1,
        timeout=120,
    ).send()
    if files:
        await _process_transcript_file(s, files[0])
    else:
        await cl.Message(content="No file received. Try again.").send()


@cl.action_callback("paste_new_transcript")
async def on_paste_new_transcript(action: cl.Action):
    s = _state()
    s["_expecting_paste"] = True
    _save(s)
    await cl.Message(content="📝 Paste your transcript text and press Enter:").send()


# ── Task Agent ────────────────────────────────────────────────────────────────

@cl.action_callback("run_task_agent")
async def on_run_task_agent(action: cl.Action):
    s          = _state()
    transcript = s["current_transcript"]
    if not transcript.strip():
        await cl.Message(content="❌ No transcript found. Please upload one first.").send()
        return

    async with cl.Step(name="Task Agent", type="tool") as step:
        step.input = "Analyzing transcript with Gemini AI..."
        try:
            result = await asyncio.to_thread(call_task_agent, transcript)
            s["task_output"] = result
            s["approved_requirements"] = None
            _reset_pipeline(s)
            _save(s)
            asyncio.create_task(_ingest_to_rag(
                (s["selected_project"] or {}).get("id", ""),
                _task_output_to_text(result), "task_agent_output.txt"
            ))
            step.output = (
                f"Extracted {len(result.requirements or [])} requirements, "
                f"{len(result.pain_points or [])} pain points, "
                f"{len(result.constraints or [])} constraints"
            )
        except Exception as e:
            step.output = f"Failed: {e}"
            await cl.Message(content=f"❌ Task Agent failed: {e}").send()
            return

    await _show_hitl1(s)


@cl.action_callback("hitl1_approve")
async def on_hitl1_approve(action: cl.Action):
    s   = _state()
    pid = (s["selected_project"] or {}).get("id")
    s["approved_requirements"] = s["task_output"].model_dump()
    _reset_pipeline(s)
    _save(s)

    await cl.Message(content="✅ Requirements approved! Auto-running Planning & Feasibility agents…").send()

    # ── Planning ──────────────────────────────────────────────────────────────
    plan_result = None
    async with cl.Step(name="Planning Agent", type="tool") as step:
        step.input = "Generating technical architecture..."
        try:
            plan_result = await asyncio.to_thread(
                partial(call_planning_agent, s["approved_requirements"], project_id=pid)
            )
            s["plan_output"] = plan_result
            _save(s)
            asyncio.create_task(_ingest_to_rag(pid, _plan_output_to_text(plan_result), "planning_agent_output.txt"))
            step.output = f"Architecture: {plan_result.architecture_type}"
        except Exception as e:
            step.output = f"Failed: {e}"
            await cl.Message(content=f"❌ Planning Agent failed: {e}").send()

    # ── Feasibility ───────────────────────────────────────────────────────────
    if plan_result:
        async with cl.Step(name="Feasibility Agent", type="tool") as step:
            step.input = "Assessing technical feasibility..."
            try:
                feas = await asyncio.to_thread(
                    partial(call_feasibility_agent, s["approved_requirements"], plan_result.model_dump())
                )
                s["feasibility_output"] = feas
                _save(s)
                asyncio.create_task(_ingest_to_rag(pid, _feasibility_output_to_text(feas), "feasibility_agent_output.txt"))
                step.output = f"Complexity: {feas.complexity_level} | Confidence: {getattr(feas,'feasibility_confidence','—')}"
            except Exception as e:
                step.output = f"Failed: {e}"
                await cl.Message(content=f"❌ Feasibility Agent failed: {e}").send()

    if s["plan_output"]:
        await _show_planning_result(s)
    if s["feasibility_output"]:
        await _show_feasibility_result(s)
        await _show_hitl2(s)


@cl.action_callback("hitl1_regen")
async def on_hitl1_regen(action: cl.Action):
    s = _state()
    res = await cl.AskUserMessage(
        content=(
            "💬 **What should the Task Agent change or improve?**\n\n"
            "Examples: *\"Add more focus on security requirements\"*, "
            "*\"The pain points are too generic\"*, *\"Split requirement 3 into two\"*\n\n"
            "*(Press Enter without typing to regenerate with no feedback)*"
        ),
        timeout=300,
    ).send()
    feedback = res["output"].strip() if res else ""

    async with cl.Step(name="Task Agent (Regenerate)", type="tool") as step:
        step.input = f"Feedback: {feedback or 'none'}"
        try:
            result = await asyncio.to_thread(
                partial(call_task_agent, s["current_transcript"], feedback=feedback)
            )
            s["task_output"] = result
            s["approved_requirements"] = None
            _reset_pipeline(s)
            _save(s)
            asyncio.create_task(_ingest_to_rag(
                (s["selected_project"] or {}).get("id", ""),
                _task_output_to_text(result), "task_agent_output.txt"
            ))
            step.output = f"Extracted {len(result.requirements or [])} requirements"
        except Exception as e:
            step.output = f"Failed: {e}"
            await cl.Message(content=f"❌ Regeneration failed: {e}").send()
            return

    await _show_hitl1(s)


# ── HITL #2 ───────────────────────────────────────────────────────────────────

@cl.action_callback("hitl2_approve")
async def on_hitl2_approve(action: cl.Action):
    s = _state()
    s["approved_plan"]        = s["plan_output"].model_dump()
    s["approved_feasibility"] = s["feasibility_output"].model_dump()
    _save(s)
    await cl.Message(content="✅ Plan & Feasibility approved! Ready for Estimation Agent.").send()
    await _show_estimation_step(s)


@cl.action_callback("hitl2_regen_plan")
async def on_hitl2_regen_plan(action: cl.Action):
    s = _state()
    res = await cl.AskUserMessage(
        content=(
            "💬 **What should the Planning Agent change about the architecture?**\n\n"
            "Examples: *\"Use microservices instead of monolith\"*, "
            "*\"Switch frontend to Vue.js\"*, *\"Include a caching layer\"*\n\n"
            "*(Press Enter to regenerate with no feedback)*"
        ),
        timeout=300,
    ).send()
    feedback = res["output"].strip() if res else ""
    pid      = (s["selected_project"] or {}).get("id")

    plan_result = None
    async with cl.Step(name="Planning Agent (Regenerate)", type="tool") as step:
        step.input = f"Feedback: {feedback or 'none'}"
        try:
            plan_result = await asyncio.to_thread(
                partial(call_planning_agent, s["approved_requirements"], project_id=pid, feedback=feedback)
            )
            s["plan_output"] = plan_result
            s["feasibility_output"] = None
            s["approved_plan"] = s["approved_feasibility"] = None
            s["estimation_output"] = s["approved_estimation"] = s["report_output"] = None
            _save(s)
            asyncio.create_task(_ingest_to_rag(pid, _plan_output_to_text(plan_result), "planning_agent_output.txt"))
            step.output = f"Architecture: {plan_result.architecture_type}"
        except Exception as e:
            step.output = f"Failed: {e}"
            await cl.Message(content=f"❌ Plan regeneration failed: {e}").send()
            return

    await _show_planning_result(s)

    async with cl.Step(name="Feasibility Agent", type="tool") as step:
        step.input = "Re-running feasibility on updated plan..."
        try:
            feas = await asyncio.to_thread(
                partial(call_feasibility_agent, s["approved_requirements"], plan_result.model_dump())
            )
            s["feasibility_output"] = feas
            _save(s)
            asyncio.create_task(_ingest_to_rag(pid, _feasibility_output_to_text(feas), "feasibility_agent_output.txt"))
            step.output = f"Complexity: {feas.complexity_level}"
        except Exception as e:
            step.output = f"Failed: {e}"
            await cl.Message(content=f"❌ Feasibility failed: {e}").send()
            return

    await _show_feasibility_result(s)
    await _show_hitl2(s)


@cl.action_callback("hitl2_rerun_feas")
async def on_hitl2_rerun_feas(action: cl.Action):
    s = _state()
    res = await cl.AskUserMessage(
        content=(
            "💬 **What should the Feasibility Agent reconsider?**\n\n"
            "Examples: *\"Re-evaluate the complexity — the team has prior AI experience\"*, "
            "*\"The risk around third-party APIs seems overstated\"*\n\n"
            "*(Press Enter to re-run with no feedback)*"
        ),
        timeout=300,
    ).send()
    feedback = res["output"].strip() if res else ""

    async with cl.Step(name="Feasibility Agent (Re-run)", type="tool") as step:
        step.input = f"Feedback: {feedback or 'none'}"
        try:
            result = await asyncio.to_thread(
                partial(call_feasibility_agent, s["approved_requirements"],
                        s["plan_output"].model_dump(), feedback=feedback)
            )
            s["feasibility_output"] = result
            s["approved_feasibility"] = s["estimation_output"] = s["approved_estimation"] = s["report_output"] = None
            _save(s)
            asyncio.create_task(_ingest_to_rag(
                (s["selected_project"] or {}).get("id", ""),
                _feasibility_output_to_text(result), "feasibility_agent_output.txt"
            ))
            step.output = f"Complexity: {result.complexity_level}"
        except Exception as e:
            step.output = f"Failed: {e}"
            await cl.Message(content=f"❌ Feasibility re-run failed: {e}").send()
            return

    await _show_feasibility_result(s)
    await _show_hitl2(s)


# ── Estimation ────────────────────────────────────────────────────────────────

@cl.action_callback("toggle_mvp")
async def on_toggle_mvp(action: cl.Action):
    s = _state()
    s["include_mvp"] = not s.get("include_mvp", False)
    _save(s)
    await _show_estimation_step(s)


@cl.action_callback("run_estimation")
async def on_run_estimation(action: cl.Action):
    s       = _state()
    pid     = (s["selected_project"] or {}).get("id")
    inc_mvp = s.get("include_mvp", False)

    rag_context = ""
    if pid:
        try:
            chunks = await asyncio.to_thread(partial(_retrieve_context, pid, "effort estimation work breakdown structure", 5))
            rag_context = _format_context(chunks)
        except Exception:
            pass

    async with cl.Step(name="Estimation Agent", type="tool") as step:
        step.input = "Generating Work Breakdown Structure & effort estimates..."
        try:
            result = await asyncio.to_thread(partial(
                run_estimation_agent,
                s["approved_requirements"],
                s["plan_output"].model_dump(),
                s["feasibility_output"].model_dump(),
                transcript=s.get("current_transcript", ""),
                include_mvp=inc_mvp,
                rag_context=rag_context,
            ))
            s["estimation_output"] = result
            s["approved_estimation"] = s["report_output"] = None
            _save(s)
            asyncio.create_task(_ingest_to_rag(pid, _estimation_output_to_text(result), "estimation_agent_output.txt"))
            step.output = f"Total: {result.totals.total_hours} hrs across {len(result.estimations)} items"
        except Exception as e:
            step.output = f"Failed: {e}"
            await cl.Message(content=f"❌ Estimation Agent failed: {e}").send()
            return

    await _show_estimation_result(s)
    await _show_hitl3(s)


# ── HITL #3 ───────────────────────────────────────────────────────────────────

@cl.action_callback("hitl3_approve")
async def on_hitl3_approve(action: cl.Action):
    s = _state()
    s["approved_estimation"] = s["estimation_output"].model_dump()
    _save(s)
    await cl.Message(content="✅ Estimation approved! Ready to generate the Final Report.").send()
    await _show_report_step(s)


@cl.action_callback("hitl3_regen")
async def on_hitl3_regen(action: cl.Action):
    s = _state()
    res = await cl.AskUserMessage(
        content=(
            "💬 **What should the Estimation Agent change?**\n\n"
            "Examples: *\"The frontend hours seem too low\"*, "
            "*\"Add a dedicated QA/testing module\"*, "
            "*\"Split module B into two separate rows\"*\n\n"
            "*(Press Enter to regenerate with no feedback)*"
        ),
        timeout=300,
    ).send()
    feedback = res["output"].strip() if res else ""
    pid      = (s["selected_project"] or {}).get("id")
    inc_mvp  = s.get("include_mvp", False)

    async with cl.Step(name="Estimation Agent (Regenerate)", type="tool") as step:
        step.input = f"Feedback: {feedback or 'none'}"
        try:
            result = await asyncio.to_thread(partial(
                call_estimation_agent,
                s["approved_requirements"],
                s["plan_output"].model_dump(),
                s["feasibility_output"].model_dump(),
                project_id=pid,
                transcript=s.get("current_transcript", ""),
                include_mvp=inc_mvp,
                feedback=feedback,
            ))
            s["estimation_output"] = result
            s["approved_estimation"] = s["report_output"] = None
            _save(s)
            asyncio.create_task(_ingest_to_rag(pid, _estimation_output_to_text(result), "estimation_agent_output.txt"))
            t_data = result.totals.model_dump()
            step.output = f"Total: {t_data.get('total_hours', 0)} hrs"
        except Exception as e:
            step.output = f"Failed: {e}"
            await cl.Message(content=f"❌ Estimation regeneration failed: {e}").send()
            return

    await _show_estimation_result(s)
    await _show_hitl3(s)


# ── Report ────────────────────────────────────────────────────────────────────

@cl.action_callback("upload_ref_docs")
async def on_upload_ref_docs(action: cl.Action):
    s = _state()
    await _handle_rag_upload(s)


@cl.action_callback("download_docx")
async def on_download_docx(action: cl.Action):
    s = _state()
    report = s.get("report_output")
    if not report:
        await cl.Message(content="❌ No report found — run the pipeline first.").send()
        return
    try:
        buf = await asyncio.to_thread(generate_docx, report)
        data = buf.read()
        if not data:
            raise ValueError("DOCX generator returned empty bytes")
        proj_name = (s.get("selected_project") or {}).get("name", "project").replace(" ", "_")
        await cl.Message(
            content="📄 **DOCX Report ready:**",
            elements=[cl.File(
                name=f"{proj_name}_report.docx",
                content=data,
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                display="inline",
            )],
        ).send()
    except Exception as e:
        await cl.Message(content=f"❌ DOCX generation failed: {e}").send()


@cl.action_callback("generate_report")
async def on_generate_report(action: cl.Action):
    s    = _state()
    req  = s["approved_requirements"] or (s["task_output"].model_dump() if s["task_output"] else {})
    plan = s["approved_plan"] or (s["plan_output"].model_dump() if s["plan_output"] else {})
    feas = s["approved_feasibility"] or (s["feasibility_output"].model_dump() if s["feasibility_output"] else {})
    est  = s["approved_estimation"] or (s["estimation_output"].model_dump() if s["estimation_output"] else {})

    missing = [name for name, val in [("requirements", req), ("plan", plan), ("feasibility", feas), ("estimation", est)] if not val]
    if missing:
        await cl.Message(content=f"❌ Cannot generate report — missing: {', '.join(missing)}. Please complete those steps first.").send()
        return

    async with cl.Step(name="Report Agent", type="tool") as step:
        step.input = "Generating 11-section consulting report..."
        try:
            result = await asyncio.to_thread(partial(call_report_agent, req, plan, feas, est))
            s["report_output"] = result.model_dump()
            _save(s)
            step.output = "Report generated successfully"
        except Exception as e:
            step.output = f"Failed: {e}"
            await cl.Message(content=f"❌ Report generation failed: {e}").send()
            return

    await _show_report_result(s)

import sys
from pathlib import Path

root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

# Force UTF-8 output on Windows (prevents charmap errors from emoji in logs)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import asyncio
import io
import re
import threading
from datetime import datetime
from functools import partial
from typing import Optional

import chainlit as cl
import pandas as pd

import backend.supabase as db
from backend.agents.task_agent import run_task_agent
from backend.agents.planning_agent import run_planning_agent
from backend.agents.feasibility_agent import run_feasibility_agent
from backend.agents.estimation_agent import run_estimation_agent, run_estimation_pass1, run_estimation_pass2
from backend.agents.report_agent import run_report_agent
from backend.rag.retrival import retrieve_context as _retrieve_context, format_context_for_prompt as _format_context
from backend.report_generator import generate_docx, generate_pdf, generate_json, generate_markdown
from backend.rag.ingestion import ingest_document, list_project_documents, extract_text
from backend.rag.retrival import retrieve_context, format_context_for_prompt
from backend.llm_client import generate_with_fallback
from backend.rag.cache import search_cache, store_cache
from backend.langfuse_client import create_trace, flush


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


def _bg(coro) -> None:
    """Schedule a coroutine to run AFTER the current callback returns.
    This prevents Chainlit from tracking it as part of the current action,
    which would keep buttons greyed until the task finishes."""
    loop = asyncio.get_event_loop()
    loop.call_soon(lambda: asyncio.ensure_future(coro))


def _to_dict(obj) -> dict:
    """Safely convert a Pydantic model or dict to a plain dict."""
    if obj is None:
        return {}
    if isinstance(obj, dict):
        return obj
    return obj.model_dump()


# ─────────────────────────────────────────────────────────────────────────────
# Langfuse pipeline trace — ONE trace per pipeline run, shared across all agents.
# Stored in a dedicated session slot (NOT in `s`) so it is never serialized to DB.
# ─────────────────────────────────────────────────────────────────────────────

def _start_trace(s: dict):
    """Begin a fresh Langfuse trace for a new pipeline run and store it on the session."""
    proj = s.get("selected_project") or {}
    try:
        trace = create_trace(
            name="poc-pipeline",
            session_id=str(proj.get("id") or "session"),
            metadata={"project": proj.get("name", "")},
        )
    except Exception as e:
        print(f"[Langfuse] start trace failed: {e}")
        trace = None
    cl.user_session.set("pipeline_trace", trace)
    return trace


def _trace(s: dict):
    """Return the current pipeline trace, starting one if none exists yet."""
    t = cl.user_session.get("pipeline_trace")
    if t is None:
        t = _start_trace(s)
    return t


def _end_trace(output=None) -> None:
    """Finalize the pipeline trace (attach overall output) and flush to Langfuse."""
    trace = cl.user_session.get("pipeline_trace")
    if trace is not None and output is not None:
        try:
            trace.update(output=output)
        except Exception:
            pass
    try:
        flush()
    except Exception:
        pass
    cl.user_session.set("pipeline_trace", None)


def _db_save(s: dict) -> None:
    """Persist current pipeline outputs to Supabase (fire-and-forget, never raises)."""
    pid = (s.get("selected_project") or {}).get("id")
    if not pid:
        return
    try:
        db.save_pipeline_run(pid, s)
    except Exception as e:
        print(f"[Persist] save error: {e}")


def _db_load(s: dict) -> None:
    """Restore pipeline outputs from Supabase into session state, re-hydrating Pydantic models."""
    pid = (s.get("selected_project") or {}).get("id")
    if not pid:
        return
    try:
        row = db.load_pipeline_run(pid)
        if not row:
            return
        from backend.schemas.task_schema import TaskAgentOutput
        from backend.schemas.plan_schema import PlanningAgentOutput
        from backend.schemas.feasibility_schema import FeasibilityAgentOutput
        from backend.schemas.estimation_schema import EstimationAgentOutput

        _schema_map = {
            "task_output": TaskAgentOutput,
            "plan_output": PlanningAgentOutput,
            "feasibility_output": FeasibilityAgentOutput,
            "estimation_output": EstimationAgentOutput,
        }
        for field in ("task_output", "approved_requirements", "plan_output",
                      "feasibility_output", "estimation_output", "approved_estimation"):
            val = row.get(field)
            if val:
                cls = _schema_map.get(field)
                if cls and isinstance(val, dict):
                    try:
                        s[field] = cls(**val)
                    except Exception as hydrate_err:
                        print(f"[Persist] hydration failed for {field}: {hydrate_err}")
                        s[field] = val  # keep raw dict as fallback
                else:
                    s[field] = val
        print(f"[Persist] Restored pipeline for project {pid}")
    except Exception as e:
        print(f"[Persist] load error: {e}")


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


def _get_all_tasks(estimation) -> list:
    """Helper to flatten the nested Functionality -> Module -> Task structure."""
    if isinstance(estimation, dict):
        funcs = estimation.get("functionalities") or []
    else:
        funcs = getattr(estimation, "functionalities", []) or []

    tasks = []
    for f in funcs:
        f_data = f if isinstance(f, dict) else f.model_dump()
        fname = f_data.get("name", "")
        for m in f_data.get("modules", []):
            mname = m.get("module", "")
            for t in m.get("tasks", []):
                t_dict = dict(t)
                t_dict["functionality"] = fname
                t_dict["module"] = mname
                tasks.append(t_dict)
    return tasks


def _build_estimation_df(estimation, include_mvp: bool = False) -> pd.DataFrame:
    if isinstance(estimation, dict):
        from backend.schemas.estimation_schema import EstimationAgentOutput
        try:
            estimation = EstimationAgentOutput(**estimation)
        except Exception:
            return pd.DataFrame({"Error": ["Invalid estimation format"]})

    stack_cols = estimation.stack_columns or []
    fixed_start = ["No", "Functionality Type", "Module", "Task", "Sub-tasks", "Features", "Interface Type"]
    fixed_end   = ["Complexity", "Tech Remarks", "BA Remarks"]
    all_cols    = fixed_start + stack_cols + ["Estimated Hours", "Is MVP"] + fixed_end

    rows = []
    for item in _get_all_tasks(estimation):
        data = item if isinstance(item, dict) else item.model_dump()
        involvement = data.get("stack_involvement") or {}
        sub_tasks = data.get("sub_tasks") or []
        row = {
            "No":               data.get("no", ""),
            "Functionality Type": data.get("functionality", ""),
            "Module":           data.get("module", ""),
            "Task":             data.get("task", ""),
            "Sub-tasks":        "\n".join(f"• {s}" for s in sub_tasks),
            "Features":         data.get("features", ""),
            "Interface Type":   data.get("interface_type", ""),
            "Estimated Hours":  data.get("estimated_hours", 0),
            "Is MVP":           "Yes" if data.get("is_mvp", True) else "No",
            "Complexity":       data.get("complexity", ""),
            "Tech Remarks":     data.get("tech_remarks", ""),
            "BA Remarks":       "",
        }
        for col in stack_cols:
            row[col] = "✓" if involvement.get(col) else ""
        rows.append(row)

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
    if isinstance(estimation, dict):
        from backend.schemas.estimation_schema import EstimationAgentOutput
        try:
            estimation = EstimationAgentOutput(**estimation)
        except Exception:
            return ""
    lines = ["=== Work Breakdown Structure ==="]
    stack_cols = estimation.stack_columns or []
    for item in _get_all_tasks(estimation):
        data = item if isinstance(item, dict) else item.model_dump()
        involvement = data.get("stack_involvement") or {}
        active = [c for c in stack_cols if involvement.get(c)]
        sub_tasks = data.get("sub_tasks") or []
        sub_txt = ("; ".join(sub_tasks)) if sub_tasks else ""
        lines.append(
            f"[{data.get('no','')}] {data.get('functionality','')} > {data.get('module','')} > {data.get('task','')} "
            f"| {data.get('features','')} "
            + (f"| Sub-tasks: {sub_txt} " if sub_txt else "")
            + f"| Interface: {data.get('interface_type','')} "
            f"| Stacks: {', '.join(active)} "
            f"| Remarks: {data.get('tech_remarks','')}"
        )
    if estimation.assumptions:
        lines.append("\n=== Assumptions ===")
        lines.extend(f"- {a}" for a in estimation.assumptions)
    return "\n".join(lines)


def _build_rag_context(project_id: str | None, requirements: dict) -> str:
    if not project_id:
        return ""
    try:
        query = " ".join(
            requirements.get("pain_points", []) +
            requirements.get("requirements", []) +
            requirements.get("business_goals", [])
        )[:1500]
        chunks = retrieve_context(project_id, query)
        return format_context_for_prompt(chunks)
    except Exception:
        return ""


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


async def _stream_answer(prompt: str, agent_name: str = "qa_agent"):
    """Async generator that yields Gemini tokens, falling back to a blocking call on error."""
    from backend.llm_client import stream_gemini
    loop = asyncio.get_event_loop()
    queue: asyncio.Queue = asyncio.Queue()

    def _run():
        try:
            for token in stream_gemini(prompt):
                loop.call_soon_threadsafe(queue.put_nowait, token)
        except Exception:
            try:
                result = generate_with_fallback(prompt, agent_name=agent_name)
                loop.call_soon_threadsafe(queue.put_nowait, result)
            except Exception as e:
                loop.call_soon_threadsafe(queue.put_nowait, f"Failed: {e}")
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, None)

    threading.Thread(target=_run, daemon=True).start()
    while True:
        token = await queue.get()
        if token is None:
            break
        yield token


_QA_HISTORY_LIMIT = 6  # keep last 6 turns (3 Q&A pairs) in the prompt

_SMALL_TALK_PATTERNS = {
    "hi", "hey", "hello", "hii", "helo", "heya", "howdy",
    "thanks", "thank you", "thankyou", "thx", "ty",
    "ok", "okay", "got it", "sure", "cool", "great", "nice", "awesome",
    "bye", "goodbye", "see you", "later",
    "how are you", "how r u", "whats up", "what's up", "sup",
    "who are you", "what are you", "what can you do",
    "good morning", "good evening", "good afternoon", "good night",
    "yes", "no", "yep", "nope", "yup",
}

def _is_small_talk(text: str) -> bool:
    """Return True if the message is a greeting or casual small talk that needs no RAG."""
    t = text.strip().lower().rstrip("!?.").strip()
    if t in _SMALL_TALK_PATTERNS:
        return True
    # Very short messages (≤ 4 words) with no project-related keywords
    words = t.split()
    if len(words) <= 4:
        project_keywords = {"what", "how", "why", "when", "where", "which", "who",
                            "show", "list", "explain", "tell", "describe", "give",
                            "requirement", "feature", "module", "risk", "estimation",
                            "architecture", "plan", "feasibility", "report", "tech", "stack"}
        if not any(w in project_keywords for w in words):
            return True
    return False


async def _qa_answer(s: dict, question: str) -> None:
    """Answer Q&A questions — skips RAG for greetings/small talk, full pipeline for real questions."""
    proj_name  = (s["selected_project"] or {}).get("name", "this project")
    project_id = (s["selected_project"] or {}).get("id", "")
    history    = s.get("qa_history") or []

    def _history_block() -> str:
        if not history:
            return ""
        lines = ["[CONVERSATION HISTORY]"]
        for turn in history[-_QA_HISTORY_LIMIT:]:
            lines.append(f"User: {turn['q']}")
            lines.append(f"Assistant: {turn['a']}")
        lines.append("[END OF HISTORY]")
        return "\n".join(lines)

    # ── Fast path: small talk / greetings — no RAG, no query expansion ────────
    if _is_small_talk(question):
        prompt = (
            f"You are a helpful assistant for the project \"{proj_name}\". "
            f"The user sent a casual message. Reply naturally and briefly.\n\n"
            f"{_history_block()}\n\nUser: {question}"
        )
        msg = cl.Message(content="")
        await msg.send()
        answer_parts = []
        try:
            async for token in _stream_answer(prompt, agent_name="qa_agent"):
                answer_parts.append(token)
                await msg.stream_token(token)
        except Exception as e:
            await msg.stream_token(f"❌ {e}")
        await msg.update()
        answer = "".join(answer_parts)
        history.append({"q": question, "a": answer})
        s["qa_history"] = history
        _save(s)
        return

    # ── Full path: real project question ──────────────────────────────────────
    if not project_id:
        await cl.Message(content="❌ No project selected — cannot search project documents.").send()
        return

    # ── Semantic cache check — return instantly if similar question was answered before ──
    cached = await asyncio.to_thread(search_cache, project_id, question)
    if cached:
        await cl.Message(content=cached).send()
        history.append({"q": question, "a": cached})
        s["qa_history"] = history
        _save(s)
        return

    # Query expansion — only for longer/complex questions (> 8 words); skip for short ones
    import json as _json
    all_queries = [question]
    if len(question.split()) > 8:
        expand_prompt = (
            f"Generate 2 different search queries to retrieve relevant information for this question "
            f"from a software project document. Approach the topic from different angles "
            f"(conceptual, keyword-focused). Return only a JSON array of 2 strings. "
            f"No explanation, no markdown.\nQuestion: {question}"
        )
        try:
            expand_raw = await asyncio.to_thread(partial(generate_with_fallback, expand_prompt, agent_name="query_expander"))
            expand_raw = re.sub(r"^```(?:json)?\s*", "", expand_raw.strip(), flags=re.MULTILINE)
            expand_raw = re.sub(r"\s*```$", "", expand_raw.strip(), flags=re.MULTILINE)
            extra_queries = _json.loads(expand_raw.strip())
            if isinstance(extra_queries, list):
                all_queries = [question] + extra_queries[:2]
        except Exception:
            pass  # fall back to original question only

    # RAG retrieval — run all query angles in parallel
    async with cl.Step(name="Searching Documents", type="retrieval") as step:
        step.input = question
        try:
            tasks = [asyncio.to_thread(partial(retrieve_context, project_id, q, 6)) for q in all_queries]
            results_per_query = await asyncio.gather(*tasks, return_exceptions=True)
            seen_ids: set = set()
            merged_chunks: list = []
            for results in results_per_query:
                if isinstance(results, Exception):
                    continue
                for c in results:
                    cid = c.get("id") or c.get("chunk_text", "")[:80]
                    if cid not in seen_ids:
                        seen_ids.add(cid)
                        merged_chunks.append(c)
            merged_chunks.sort(key=lambda x: x.get("similarity", 0), reverse=True)
            chunks = merged_chunks[:10]
            context = format_context_for_prompt(chunks)
            step.output = f"Found {len(chunks)} unique chunk(s) across {len(all_queries)} search angle(s)"
        except Exception as e:
            chunks = []
            context = ""
            step.output = f"Retrieval failed: {e}"

    prompt = (
        f"You are an AI assistant answering questions about the software project \"{proj_name}\".\n\n"
        f"{context if context else '(No indexed documents found — answer from general knowledge.)'}\n\n"
        f"{_history_block()}\n\n"
        f"Question: {question}\n\n"
        f"Answer concisely and accurately. Reference specific sections from the documents when possible. "
        f"If the answer is not in the documents, say so clearly."
    )

    msg = cl.Message(content="")
    await msg.send()
    answer_parts = []
    try:
        async for token in _stream_answer(prompt, agent_name="qa_agent"):
            answer_parts.append(token)
            await msg.stream_token(token)
    except Exception as e:
        await msg.stream_token(f"❌ Failed to generate answer: {e}")
    await msg.update()
    answer = "".join(answer_parts)

    history.append({"q": question, "a": answer})
    s["qa_history"] = history
    _save(s)

    # Store in semantic cache for future similar questions (fire-and-forget)
    if not answer.startswith("❌"):
        _bg(asyncio.to_thread(store_cache, project_id, question, answer))


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
    pid = project["id"]

    # ── 1. Meeting transcript (mandatory) ────────────────────────────────────
    existing_transcript = ""
    try:
        tr = db.get_transcript(pid)
        existing_transcript = (tr or {}).get("content", "").strip()
    except Exception:
        pass

    if existing_transcript:
        s["current_transcript"] = existing_transcript
        _save(s)
        preview = existing_transcript[:300] + ("..." if len(existing_transcript) > 300 else "")
        await cl.Message(
            content=(
                f"### Step 1 — Meeting Transcript for *{project['name']}*\n\n"
                f"📄 **Saved transcript** *(first 300 chars)*:\n```\n{preview}\n```"
            ),
            actions=[
                cl.Action(name="use_existing_transcript", payload={}, label="✅ Use This Transcript"),
                cl.Action(name="upload_new_transcript",   payload={}, label="📤 Replace with New File"),
                cl.Action(name="paste_new_transcript",    payload={}, label="📝 Replace with Paste"),
                cl.Action(name="delete_transcript",       payload={"project_id": pid}, label="🗑️ Delete Transcript"),
            ],
        ).send()
    else:
        await cl.Message(
            content=(
                f"### Step 1 — Meeting Transcript for *{project['name']}*\n\n"
                f"Upload or paste the **client meeting transcript** (recording notes, call summary, etc.):"
            ),
            actions=[
                cl.Action(name="upload_new_transcript", payload={}, label="📤 Upload File (PDF/DOCX/TXT)"),
                cl.Action(name="paste_new_transcript",  payload={}, label="📝 Paste Text"),
            ],
        ).send()

    # ── 2. Reference docs (optional, completely separate) ────────────────────
    try:
        ref_docs = list_project_documents(pid)
        if ref_docs:
            doc_list = "\n".join(f"- 📎 {d['document_name']}" for d in ref_docs)
            delete_actions = [
                cl.Action(name="delete_ref_doc", payload={"doc_name": d["document_name"], "project_id": pid}, label=f"🗑️ {d['document_name']}")
                for d in ref_docs
            ]
            await cl.Message(
                content=(
                    f"**📚 Reference Documents** *(optional — already indexed for this project)*:\n{doc_list}\n\n"
                    f"These give agents extra context. You can add more, or delete individual docs below."
                ),
                actions=[
                    cl.Action(name="upload_ref_docs", payload={}, label="➕ Add More Reference Docs"),
                    *delete_actions,
                ],
            ).send()
        else:
            await cl.Message(
                content="**📚 Reference Documents** *(optional)*: No reference docs uploaded yet.",
                actions=[
                    cl.Action(name="upload_ref_docs", payload={}, label="📄 Upload Reference Docs (Optional)"),
                ],
            ).send()
    except Exception:
        pass


# ── Step 2: Task Agent ────────────────────────────────────────────────────────

async def _show_task_agent_step(s: dict) -> None:
    s["step"] = "task_agent"
    _save(s)
    await cl.Message(
        content=(
            "### Step 2 — Task Identification Agent\n\n"
            "Extracts **requirements**, **pain points**, **constraints**, **business goals**, "
            "and **technology context** from your transcript using Gemini AI."
        ),
        actions=[
            cl.Action(name="run_task_agent", payload={}, label="▶ Run Task Agent"),
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

    # Show architecture diagram — PIL renderer (reliable, no CDN)
    excalidraw_data = getattr(plan, "excalidraw_diagram", None) or {}
    if excalidraw_data.get("nodes"):
        try:
            from backend.excalidraw_utils import diagram_to_png
            png_bytes = await asyncio.to_thread(diagram_to_png, excalidraw_data)
            if png_bytes:
                img = cl.Image(name="architecture.png", content=png_bytes, display="inline")
                await cl.Message(content="**🗺️ Architecture Diagram:**", elements=[img]).send()
        except Exception as _exc:
            print(f"[Chainlit] diagram render failed: {_exc}")
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
    s["step"] = "estimation"
    _save(s)
    await cl.Message(
        content=(
            "### Step 5 — Work Breakdown Structure\n\n"
            "The agent reads all approved outputs and produces a dynamic WBS:\n\n"
            "1. Identifies project **Functionalities** (A, B, C...)\n"
            "2. Breaks each into **Modules** (A.1, A.2...)\n"
            "3. Marks which **tech disciplines** are involved per module\n"
            "4. Adds **Tech Remarks** (assumptions) — BA Remarks left blank for your team\n\n"
            "Stack columns (Frontend, Backend, AI/ML, etc.) are **fully dynamic** per project."
        ),
        actions=[
            cl.Action(name="run_estimation", payload={}, label="▶ Run Estimation Agent"),
        ],
    ).send()


async def _show_estimation_result(s: dict) -> None:
    est = s["estimation_output"]
    if isinstance(est, dict):
        from backend.schemas.estimation_schema import EstimationAgentOutput
        try:
            est = EstimationAgentOutput(**est)
            s["estimation_output"] = est
        except Exception as e:
            await cl.Message(content=f"⚠️ Could not display estimation — format error: {e}").send()
            return

    all_tasks = _get_all_tasks(est)
    total   = len(all_tasks)
    stacks  = est.stack_columns or []
    funcs   = est.functionalities or []

    # ── Summary card ──────────────────────────────────────────────────────────
    summary = [f"### 📋 Work Breakdown Structure — {total} tasks\n"]
    if funcs:
        summary.append("**Functionalities:**")
        for f in funcs:
            d = f if isinstance(f, dict) else f.model_dump()
            summary.append(f"  {d.get('letter','')}.  {d.get('name','')}")
    if stacks:
        summary.append(f"\n**Tech Disciplines:** {' | '.join(stacks)}")
    await cl.Message(content="\n".join(summary)).send()

    # ── Grouped preview by functionality ──────────────────────────────────────
    df = _build_estimation_df(est)
    preview_lines = ["```"]
    current_func = None
    count = 0
    for _, row in df.iterrows():
        if count >= 40:
            break
        func = row.get("Functionality Type", "")
        if func != current_func:
            preview_lines.append(f"\n── {func} ──")
            current_func = func
        # build concise row: No | Module | stack marks | Interface Type
        marks = "  ".join(
            f"{col}:✓" if row.get(col) == "✓" else f"{col}:·"
            for col in stacks
        )
        hours = str(row.get('Estimated Hours', 0)) + 'h'
        comp = str(row.get('Complexity', ''))
        task_label = str(row.get('Task', ''))
        preview_lines.append(f"  {str(row.get('No','')):8}  {task_label[:45]:45} {hours:>4} {comp[:4]:4}  {marks}  [{row.get('Interface Type','')}]")
        count += 1
    preview_lines.append("```")
    await cl.Message(content="\n".join(preview_lines)).send()
    if total > 40:
        await cl.Message(content=f"*Showing first 40 of {total} tasks — full table in the Excel download.*").send()

    # ── Assumptions ───────────────────────────────────────────────────────────
    if est.assumptions:
        lines = ["**Assumptions:**"]
        lines.extend(f"- {a}" for a in est.assumptions)
        await cl.Message(content="\n".join(lines)).send()

    # ── Excel download with formatting ────────────────────────────────────────
    try:
        from openpyxl.styles import PatternFill, Font, Alignment, Border, Side
        from openpyxl.utils import get_column_letter

        xl_buf = io.BytesIO()
        with pd.ExcelWriter(xl_buf, engine="openpyxl") as writer:
            df.to_excel(writer, index=False, sheet_name="WBS")
            wb = writer.book
            ws = writer.sheets["WBS"]

            # Header style
            header_fill = PatternFill("solid", fgColor="1F3864")
            header_font = Font(bold=True, color="FFFFFF", size=10)
            for cell in ws[1]:
                cell.fill = header_fill
                cell.font = header_font
                cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

            # Alternating row fill colours per functionality group
            func_colors = [
                "DCE6F1", "E2EFDA", "FFF2CC", "FCE4D6",
                "EAD1DC", "D9EAD3", "CFE2F3", "F4CCCC",
            ]
            func_map: dict = {}
            color_idx = 0
            thin = Side(style="thin", color="CCCCCC")
            border = Border(left=thin, right=thin, top=thin, bottom=thin)

            for row_idx, row in enumerate(ws.iter_rows(min_row=2), start=2):
                func_val = ws.cell(row=row_idx, column=2).value or ""
                if func_val not in func_map:
                    func_map[func_val] = func_colors[color_idx % len(func_colors)]
                    color_idx += 1
                fill = PatternFill("solid", fgColor=func_map[func_val])
                for cell in row:
                    cell.fill = fill
                    cell.border = border
                    cell.alignment = Alignment(vertical="top", wrap_text=True)

            # Column widths
            col_widths = {"No": 9, "Functionality Type": 26, "Module": 24,
                          "Task": 28, "Sub-tasks": 45,
                          "Features": 50, "Interface Type": 20,
                          "Complexity": 14, "Tech Remarks": 42, "BA Remarks": 28}
            for col_idx, col_name in enumerate(df.columns, start=1):
                width = col_widths.get(col_name, 14)
                ws.column_dimensions[get_column_letter(col_idx)].width = width

            ws.freeze_panes = "A2"
            ws.row_dimensions[1].height = 32

        await cl.Message(
            content="📥 Download full WBS (Excel):",
            elements=[cl.File(
                name="work_breakdown_structure.xlsx",
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
            from backend.excalidraw_utils import diagram_to_png
            png_bytes = await asyncio.to_thread(diagram_to_png, excalidraw_data)
            if png_bytes:
                img = cl.Image(name="architecture.png", content=png_bytes, display="inline")
                await cl.Message(content="### 07. Solution Architecture", elements=[img]).send()
                arch_sent = True
        except Exception as _exc:
            print(f"[Chainlit] Report diagram render failed: {_exc}")

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

    # ── Effort Estimation Summary (condensed — full table available in Step 5) ──
    est_obj = s.get("estimation_output")
    if est_obj:
        if isinstance(est_obj, dict):
            from backend.schemas.estimation_schema import EstimationAgentOutput
            try:
                est_obj = EstimationAgentOutput(**est_obj)
            except Exception:
                est_obj = None
    if est_obj:
        wbs   = _get_all_tasks(est_obj)
        funcs = est_obj.functionalities or []
        stacks = est_obj.stack_columns or []
        est_lines = ["### 📊 Work Breakdown Summary\n", f"**Total tasks: {len(wbs)}**"]
        if funcs:
            func_names = [
                (f if isinstance(f, dict) else f.model_dump()).get("name", "")
                for f in funcs
            ]
            est_lines.append(f"**Functionalities:** {', '.join(func_names)}")
        if stacks:
            est_lines.append(f"**Tech Disciplines:** {' | '.join(stacks)}")
        await cl.Message(content="\n".join(est_lines)).send()

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
            _bg(_ingest_to_rag(project_id, transcript, "transcript.txt", "txt"))
        report_text = _report_to_index_text(report)
        if report_text.strip():
            _bg(_ingest_to_rag(project_id, report_text, "final_report.txt", "txt"))

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
        _bg(_ingest_to_rag(project["id"], text.strip(), "transcript.txt", "txt"))
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


async def _process_multiple_transcript_files(s: dict, files: list) -> None:
    """Extract text from multiple files and concatenate into one transcript."""
    parts = []
    for f in files:
        try:
            path = getattr(f, "path", None)
            raw  = getattr(f, "content", None)
            if path:
                with open(path, "rb") as fp:
                    content = fp.read()
            elif raw:
                content = raw if isinstance(raw, bytes) else raw.encode()
            else:
                await cl.Message(content=f"⚠️ Could not read {getattr(f, 'name', 'file')} — skipped.").send()
                continue
            name = getattr(f, "name", "file.txt")
            ext  = name.rsplit(".", 1)[-1].lower() if "." in name else "txt"
            text = await asyncio.to_thread(extract_text, content, ext)
            if text.strip():
                parts.append(f"--- {name} ---\n{text.strip()}")
        except Exception as e:
            await cl.Message(content=f"⚠️ Failed to read {getattr(f, 'name', 'file')}: {e} — skipped.").send()

    if not parts:
        await cl.Message(content="❌ No text could be extracted from the uploaded files.").send()
        return
    combined = "\n\n".join(parts)
    await cl.Message(content=f"✅ Merged {len(parts)} file(s) into one transcript ({len(combined):,} chars).").send()
    await _save_transcript_text(s, combined)


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
        max_size_mb=50,
        timeout=120,
    ).send()

    if not files:
        await cl.Message(content="No files uploaded.").send()
        return

    for f in files:
        try:
            path = getattr(f, "path", None)
            if path:
                with open(path, "rb") as _f:
                    content = _f.read()
            else:
                content = f.content if isinstance(f.content, bytes) else f.content.encode()
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


from functools import wraps

def prevent_concurrent(func):
    @wraps(func)
    async def wrapper(action: cl.Action, *args, **kwargs):
        # Also quickly remove the button visually
        try:
            await action.remove()
        except Exception:
            pass
            
        if cl.user_session.get("is_processing"):
            await cl.Message(content="⏳ Please wait! A task is currently running.").send()
            return
        cl.user_session.set("is_processing", True)
        try:
            return await func(action, *args, **kwargs)
        finally:
            cl.user_session.set("is_processing", False)
    return wrapper

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
            _db_load(s)   # restore any previously saved pipeline outputs
            _save(s)

            # Determine how far the pipeline was previously completed
            has_estimation = bool(s.get("estimation_output"))
            has_plan       = bool(s.get("plan_output"))
            has_task       = bool(s.get("task_output"))

            if has_estimation or has_plan or has_task:
                stage = ("Estimation" if has_estimation else "Planning" if has_plan else "Requirements")
                await cl.Message(
                    content=(
                        f"✅ Project **{project['name']}** selected.\n\n"
                        f"🗂️ *Previous pipeline restored up to **{stage}** stage.*\n\n"
                        f"What would you like to do?"
                    ),
                    actions=[
                        cl.Action(name="resume_pipeline",  payload={}, label="▶️ Resume Pipeline"),
                        cl.Action(name="restart_pipeline", payload={"project_id": project["id"]}, label="🔄 Start Fresh"),
                    ],
                ).send()
            else:
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


@cl.action_callback("resume_pipeline")
async def on_resume_pipeline(action: cl.Action):
    """Replay all completed stage outputs in order, then land at the pending action."""
    s = _state()

    has_task    = bool(s.get("task_output"))
    has_plan    = bool(s.get("plan_output"))
    has_feas    = bool(s.get("feasibility_output"))
    has_est     = bool(s.get("estimation_output"))
    has_app_est = bool(s.get("approved_estimation"))

    # ── Replay every completed stage so the user sees the full history ────────
    if has_task:
        await _show_hitl1(s)

    if has_plan:
        await _show_planning_result(s)

    if has_feas:
        await _show_feasibility_result(s)

    if has_est:
        await _show_estimation_result(s)

    # ── Land at the current pending action ────────────────────────────────────
    if has_app_est:
        await _show_report_step(s)
    elif has_est:
        await _show_hitl3(s)
    elif has_feas or has_plan:
        await _show_hitl2(s)
    elif not has_task:
        await _show_transcript_step(s["selected_project"], s)


@cl.action_callback("restart_pipeline")
async def on_restart_pipeline(action: cl.Action):
    """Clear all pipeline outputs and start fresh from transcript step."""
    s = _state()
    s["task_output"] = None
    s["approved_requirements"] = None
    _reset_pipeline(s)
    s["current_transcript"] = ""
    _save(s)
    # Clear from DB too
    try:
        import backend.supabase as _db
        pid = (s.get("selected_project") or {}).get("id")
        if pid:
            _db.supabase.table("pipeline_runs").delete().eq("project_id", pid).execute()
    except Exception:
        pass
    await cl.Message(content="🔄 Pipeline cleared. Starting fresh…").send()
    await _show_transcript_step(s["selected_project"], s)


@cl.action_callback("use_existing_transcript")
async def on_use_existing_transcript(action: cl.Action):
    s = _state()
    await cl.Message(content="✅ Using existing transcript.").send()
    await _show_task_agent_step(s)


@cl.action_callback("delete_transcript")
async def on_delete_transcript(action: cl.Action):
    s = _state()
    pid = action.payload.get("project_id") or (s.get("selected_project") or {}).get("id")
    try:
        db.supabase.table("transcripts").delete().eq("project_id", pid).execute()
        s["current_transcript"] = ""
        s["task_output"] = None
        s["approved_requirements"] = None
        _reset_pipeline(s)
        _save(s)
        await cl.Message(content="🗑️ Transcript deleted. You can upload a new one:").send()
        await _show_transcript_step(s["selected_project"], s)
    except Exception as e:
        await cl.Message(content=f"❌ Failed to delete transcript: {e}").send()


@cl.action_callback("delete_ref_doc")
async def on_delete_ref_doc(action: cl.Action):
    s = _state()
    doc_name = action.payload.get("doc_name")
    pid      = action.payload.get("project_id") or (s.get("selected_project") or {}).get("id")
    if not doc_name or not pid:
        await cl.Message(content="❌ Could not identify document to delete.").send()
        return
    try:
        from backend.rag.ingestion import delete_project_documents
        delete_project_documents(pid, doc_name)
        await cl.Message(content=f"🗑️ **{doc_name}** deleted from reference docs.").send()
        await _show_transcript_step(s["selected_project"], s)
    except Exception as e:
        await cl.Message(content=f"❌ Failed to delete {doc_name}: {e}").send()


@cl.action_callback("upload_new_transcript")
async def on_upload_new_transcript(action: cl.Action):
    s = _state()
    files = await cl.AskFileMessage(
        content="📤 Upload transcript file(s) — PDF, DOCX, or TXT, up to 50 MB each. Multiple files will be merged:",
        accept=["*/*"],
        max_files=5,
        max_size_mb=50,
        timeout=120,
    ).send()
    if not files:
        await cl.Message(content="No file received. Try again.").send()
        return
    if len(files) == 1:
        await _process_transcript_file(s, files[0])
    else:
        await _process_multiple_transcript_files(s, files)


@cl.action_callback("paste_new_transcript")
async def on_paste_new_transcript(action: cl.Action):
    s = _state()
    s["_expecting_paste"] = True
    _save(s)
    await cl.Message(content="📝 Paste your transcript text and press Enter:").send()


# ── Task Agent ────────────────────────────────────────────────────────────────

@cl.action_callback("run_task_agent")
@prevent_concurrent
async def on_run_task_agent(action: cl.Action):
    s          = _state()
    transcript = s["current_transcript"]
    if not transcript.strip():
        await cl.Message(content="❌ No transcript found. Please upload one first.").send()
        return

    await cl.Message(content="⏳ Analyzing transcript — extracting requirements, pain points & constraints...").send()
    trace = _start_trace(s)
    async with cl.Step(name="Task Agent", type="tool") as step:
        step.input = "Analyzing transcript with Gemini AI..."
        try:
            result = await asyncio.to_thread(partial(run_task_agent, transcript, trace=trace))
            s["task_output"] = result
            s["approved_requirements"] = None
            _reset_pipeline(s)
            _save(s)
            _db_save(s)
            _bg(_ingest_to_rag(
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
@prevent_concurrent
async def on_hitl1_approve(action: cl.Action):
    s   = _state()
    pid = (s["selected_project"] or {}).get("id")
    s["approved_requirements"] = _to_dict(s["task_output"])
    _reset_pipeline(s)
    _save(s)
    _db_save(s)

    await cl.Message(content="✅ Requirements approved! Auto-running Planning & Feasibility agents…").send()
    await cl.Message(content="⏳ Running Planning Agent — designing architecture & tech stack...").send()

    trace = _trace(s)
    # ── Planning ──────────────────────────────────────────────────────────────
    plan_result = None
    async with cl.Step(name="Planning Agent", type="tool") as step:
        step.input = "Generating technical architecture..."
        try:
            rag_ctx = _build_rag_context(pid, s["approved_requirements"])
            plan_result = await asyncio.to_thread(
                partial(run_planning_agent, s["approved_requirements"], rag_context=rag_ctx, trace=trace)
            )
            s["plan_output"] = plan_result
            _save(s)
            _db_save(s)
            _bg(_ingest_to_rag(pid, _plan_output_to_text(plan_result), "planning_agent_output.txt"))
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
                    partial(run_feasibility_agent, s["approved_requirements"], plan_result.model_dump(), trace=trace)
                )
                s["feasibility_output"] = feas
                _save(s)
                _db_save(s)
                _bg(_ingest_to_rag(pid, _feasibility_output_to_text(feas), "feasibility_agent_output.txt"))
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
@prevent_concurrent
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

    await cl.Message(content="⏳ Regenerating requirements extraction...").send()
    async with cl.Step(name="Task Agent (Regenerate)", type="tool") as step:
        step.input = f"Feedback: {feedback or 'none'}"
        try:
            result = await asyncio.to_thread(
                partial(run_task_agent, s["current_transcript"], feedback=feedback, trace=_trace(s))
            )
            s["task_output"] = result
            s["approved_requirements"] = None
            _reset_pipeline(s)
            _save(s)
            _bg(_ingest_to_rag(
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
@prevent_concurrent
async def on_hitl2_approve(action: cl.Action):
    s = _state()
    s["approved_plan"]        = _to_dict(s["plan_output"])
    s["approved_feasibility"] = _to_dict(s["feasibility_output"])
    _save(s)
    await cl.Message(content="✅ Plan & Feasibility approved! Ready for Estimation Agent.").send()
    await _show_estimation_step(s)


@cl.action_callback("hitl2_regen_plan")
@prevent_concurrent
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
    await cl.Message(content="⏳ Regenerating architecture plan...").send()
    async with cl.Step(name="Planning Agent (Regenerate)", type="tool") as step:
        step.input = f"Feedback: {feedback or 'none'}"
        try:
            rag_ctx = _build_rag_context(pid, s["approved_requirements"])
            plan_result = await asyncio.to_thread(
                partial(run_planning_agent, s["approved_requirements"], rag_context=rag_ctx, feedback=feedback, trace=_trace(s))
            )
            s["plan_output"] = plan_result
            s["feasibility_output"] = None
            s["approved_plan"] = s["approved_feasibility"] = None
            s["estimation_output"] = s["approved_estimation"] = s["report_output"] = None
            _save(s)
            _bg(_ingest_to_rag(pid, _plan_output_to_text(plan_result), "planning_agent_output.txt"))
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
                partial(run_feasibility_agent, s["approved_requirements"], plan_result.model_dump(), trace=_trace(s))
            )
            s["feasibility_output"] = feas
            _save(s)
            _bg(_ingest_to_rag(pid, _feasibility_output_to_text(feas), "feasibility_agent_output.txt"))
            step.output = f"Complexity: {feas.complexity_level}"
        except Exception as e:
            step.output = f"Failed: {e}"
            await cl.Message(content=f"❌ Feasibility failed: {e}").send()
            return

    await _show_feasibility_result(s)
    await _show_hitl2(s)


@cl.action_callback("hitl2_rerun_feas")
@prevent_concurrent
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

    await cl.Message(content="⏳ Re-running feasibility assessment...").send()
    async with cl.Step(name="Feasibility Agent (Re-run)", type="tool") as step:
        step.input = f"Feedback: {feedback or 'none'}"
        try:
            result = await asyncio.to_thread(
                partial(run_feasibility_agent, s["approved_requirements"],
                        _to_dict(s["plan_output"]), feedback=feedback, trace=_trace(s))
            )
            s["feasibility_output"] = result
            s["approved_feasibility"] = s["estimation_output"] = s["approved_estimation"] = s["report_output"] = None
            _save(s)
            _bg(_ingest_to_rag(
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


@cl.action_callback("stop_estimation")
async def on_stop_estimation(action: cl.Action):
    s = _state()
    s["cancel_requested"] = True
    _save(s)
    await cl.Message(content="⏹ Stop requested — will halt after the current step finishes.").send()


@cl.action_callback("run_estimation")
@prevent_concurrent
async def on_run_estimation(action: cl.Action):
    s       = _state()
    pid     = (s["selected_project"] or {}).get("id")
    inc_mvp = s.get("include_mvp", False)
    s["cancel_requested"] = False
    _save(s)

    rag_context = ""
    if pid:
        try:
            chunks = await asyncio.to_thread(partial(_retrieve_context, pid, "effort estimation work breakdown structure", 5))
            rag_context = _format_context(chunks)
        except Exception:
            pass

    await cl.Message(
        content="⏳ Running Estimation Agent — this may take 2–5 minutes on free models...",
        actions=[cl.Action(name="stop_estimation", label="⏹ Stop", value="stop", description="Cancel after the current step")],
    ).send()
    try:
        async with cl.Step(name="Mapping structure (Pass 1)", type="tool") as step1:
            step1.input = "Identifying functionalities, modules & tech stack..."
            pass1_result = await asyncio.to_thread(partial(
                run_estimation_pass1,
                s["approved_requirements"],
                _to_dict(s["plan_output"]),
                _to_dict(s["feasibility_output"]),
                "",
                rag_context,
                _trace(s),
            ))
            n_funcs = len(pass1_result.get("functionalities") or [])
            n_mods  = sum(len(v) for v in (pass1_result.get("modules_by_func") or {}).values())
            step1.output = f"Found {n_funcs} functionalities, {n_mods} modules"

        if _state().get("cancel_requested"):
            await cl.Message(content="⏹ Estimation cancelled after Pass 1.").send()
            return

        async with cl.Step(name="Decomposing tasks (Pass 2 — parallel)", type="tool") as step2:
            step2.input = f"Breaking down {n_mods} modules into tasks..."
            result = await asyncio.to_thread(partial(
                run_estimation_pass2,
                pass1_result,
                inc_mvp,
                _trace(s),
            ))
            all_res_tasks = _get_all_tasks(result)
            step2.output = f"Generated {len(all_res_tasks)} work items"

        s["estimation_output"] = result
        s["approved_estimation"] = s["report_output"] = None
        _save(s)
        _db_save(s)
        _bg(_ingest_to_rag(pid, _estimation_output_to_text(result), "estimation_agent_output.txt"))
    except Exception as e:
        await cl.Message(content=f"❌ Estimation Agent failed: {e}").send()
        return

    await _show_estimation_result(s)
    await _show_hitl3(s)


# ── HITL #3 ───────────────────────────────────────────────────────────────────

@cl.action_callback("hitl3_approve")
@prevent_concurrent
async def on_hitl3_approve(action: cl.Action):
    s = _state()
    s["approved_estimation"] = _to_dict(s["estimation_output"])
    _save(s)
    _db_save(s)
    await cl.Message(content="✅ Estimation approved! Ready to generate the Final Report.").send()
    await _show_report_step(s)


@cl.action_callback("hitl3_regen")
@prevent_concurrent
async def on_hitl3_regen(action: cl.Action):
    s = _state()
    s["cancel_requested"] = False
    _save(s)
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

    rag_context = ""
    if pid:
        try:
            chunks = await asyncio.to_thread(partial(_retrieve_context, pid, "effort estimation work breakdown structure", 5))
            rag_context = _format_context(chunks)
        except Exception:
            pass

    await cl.Message(
        content="⏳ Regenerating Estimation — this may take 2–5 minutes...",
        actions=[cl.Action(name="stop_estimation", label="⏹ Stop", value="stop", description="Cancel after the current step")],
    ).send()
    try:
        async with cl.Step(name="Mapping structure (Pass 1)", type="tool") as step1:
            step1.input = f"Feedback: {feedback or 'none'} — re-identifying structure..."
            pass1_result = await asyncio.to_thread(partial(
                run_estimation_pass1,
                s["approved_requirements"],
                _to_dict(s["plan_output"]),
                _to_dict(s["feasibility_output"]),
                feedback,
                rag_context,
                _trace(s),
            ))
            n_funcs = len(pass1_result.get("functionalities") or [])
            n_mods  = sum(len(v) for v in (pass1_result.get("modules_by_func") or {}).values())
            step1.output = f"Found {n_funcs} functionalities, {n_mods} modules"

        if _state().get("cancel_requested"):
            await cl.Message(content="⏹ Estimation cancelled after Pass 1.").send()
            return

        async with cl.Step(name="Decomposing tasks (Pass 2 — parallel)", type="tool") as step2:
            step2.input = f"Breaking down {n_mods} modules into tasks..."
            result = await asyncio.to_thread(partial(
                run_estimation_pass2,
                pass1_result,
                inc_mvp,
                _trace(s),
            ))
            all_res_tasks = _get_all_tasks(result)
            step2.output = f"Regenerated {len(all_res_tasks)} work items"

        s["estimation_output"] = result
        s["approved_estimation"] = s["report_output"] = None
        _save(s)
        _db_save(s)
        _bg(_ingest_to_rag(pid, _estimation_output_to_text(result), "estimation_agent_output.txt"))
    except Exception as e:
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
@prevent_concurrent
async def on_generate_report(action: cl.Action):
    s    = _state()
    req  = s["approved_requirements"] or _to_dict(s.get("task_output"))
    plan = s["approved_plan"] or _to_dict(s.get("plan_output"))
    feas = s["approved_feasibility"] or _to_dict(s.get("feasibility_output"))
    est  = s["approved_estimation"] or _to_dict(s.get("estimation_output"))

    missing = [name for name, val in [("requirements", req), ("plan", plan), ("feasibility", feas), ("estimation", est)] if not val]
    if missing:
        await cl.Message(content=f"❌ Cannot generate report — missing: {', '.join(missing)}. Please complete those steps first.").send()
        return

    await cl.Message(content="⏳ Generating final report — this may take a few minutes...").send()
    async with cl.Step(name="Report Agent", type="tool") as step:
        step.input = "Generating 11-section consulting report..."
        try:
            result = await asyncio.to_thread(partial(run_report_agent, req, plan, feas, est, trace=_trace(s)))
            s["report_output"] = result.model_dump()
            _save(s)
            step.output = "Report generated successfully"
            # Pipeline complete — attach overall output and flush the single trace.
            _end_trace(output={"report_sections": list((s["report_output"] or {}).keys())})
        except Exception as e:
            step.output = f"Failed: {e}"
            await cl.Message(content=f"❌ Report generation failed: {e}").send()
            _end_trace()
            return

    await _show_report_result(s)

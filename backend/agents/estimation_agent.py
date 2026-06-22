import os
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dotenv import load_dotenv
from backend.schemas.estimation_schema import EstimationAgentOutput, EstimationFunctionality, EstimationModule, EstimationTask
from backend.llm_client import generate_with_fallback
from backend.agents.json_utils import extract_json

load_dotenv()

if not os.getenv("GEMINI_API_KEY", "").strip() and not os.getenv("OPENROUTER_API_KEY", "").strip():
    raise ValueError("No API key found. Set GEMINI_API_KEY or OPENROUTER_API_KEY in your .env file.")


def _recover_items(text: str) -> list:
    """
    Extract every fully-closed JSON object from the 'items' array in truncated text.
    Immune to truncation at any position — stops before the first incomplete object.
    """
    pos = text.find('"items"')
    if pos == -1:
        return []
    arr = text.find('[', pos)
    if arr == -1:
        return []

    items, pos = [], arr + 1
    while pos < len(text):
        while pos < len(text) and text[pos] in ' \t\n\r,':
            pos += 1
        if pos >= len(text) or text[pos] in (']', '}'):
            break
        if text[pos] != '{':
            break

        depth, in_s, esc, end = 0, False, False, None
        for i in range(pos, len(text)):
            ch = text[i]
            if esc:             esc = False;  continue
            if ch == '\\' and in_s: esc = True; continue
            if ch == '"':       in_s = not in_s; continue
            if in_s:            continue
            if ch == '{':       depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:  end = i; break

        if end is None:
            break
        try:
            items.append(json.loads(text[pos:end + 1]))
        except json.JSONDecodeError:
            break
        pos = end + 1

    return items


# ═══════════════════════════════════════════════════════════════════
# PASS 1 — Identify functionalities + modules (small, fast output)
# ═══════════════════════════════════════════════════════════════════
PASS1_PROMPT = """
You are an Expert Project Manager and Solution Architect.

Your ONLY job in this step is to map the SKELETON of an end-to-end Work Breakdown
Structure for the project described below. You will NOT yet break things into tasks —
that happens in a later step. Keep output small and precise.

You will receive Approved Requirements, Architecture Plan, and Feasibility Analysis.
These are your ONLY source of truth. Do NOT invent anything not present in the inputs.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 1 — IDENTIFY STACK DISCIPLINES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Read the Architecture Plan. Identify which discipline areas this project genuinely needs.
Choose ONLY from:
  Frontend | Backend | AI/ML | DevOps | Cloud | Mobile | Data Engineering | QA | Security
Output ONLY disciplines that actually exist in THIS project's tech stack as "stack_columns".

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 2 — IDENTIFY FUNCTIONALITIES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Group the ENTIRE project into major functional areas. Label them A, B, C, D...
Example: A → User Management & Authentication, B → AI Conversation Engine,
         C → Reporting & Analytics, D → Infrastructure & DevOps.
Be exhaustive — cover DB, API, UI, AI, Cloud, Security, QA, DevOps end-to-end.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 3 — IDENTIFY MODULES PER FUNCTIONALITY
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
For each functionality, list the specific deliverable MODULES, numbered A.1, A.2, B.1...
A module is ONE specific thing being built (e.g. "Login Flow", "RBAC", "RAG Pipeline").
For each module give a ONE-LINE scope and mark which disciplines are involved.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
COMPLETENESS CHECK (do this before output)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
✅ Every requirement maps to at least one module
✅ Every architecture component has a module
✅ Infrastructure, Security, Testing, CI/CD all covered
✅ Every discipline in stack_columns appears true in at least one module

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
OUTPUT FORMAT — return ONLY valid JSON, no markdown, no prose
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{{
  "stack_columns": ["Frontend", "Backend", "AI/ML", "DevOps", "Cloud"],
  "functionalities": [
    {{"letter": "A", "name": "User Management & Authentication"}},
    {{"letter": "B", "name": "AI Conversation Engine"}}
  ],
  "modules": [
    {{
      "no": "A.1",
      "functionality": "User Management & Authentication",
      "module": "Login Flow",
      "scope": "Email/password authentication with JWT issuance and error handling",
      "interface_type": "Web + Backend",
      "stack_involvement": {{"Frontend": true, "Backend": true, "AI/ML": false, "DevOps": false, "Cloud": false}}
    }}
  ]
}}

STRICT RULES:
- "no" for modules is ALWAYS "<Letter>.<n>" like "A.1", "B.3" — never a plain integer.
- stack_involvement MUST include ALL disciplines from stack_columns (true/false), at least one true.
- Return ONLY the JSON object.

{feedback_section}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
INPUTS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
APPROVED REQUIREMENTS:
{requirements}

APPROVED ARCHITECTURE PLAN:
{plan}

APPROVED FEASIBILITY ANALYSIS:
{feasibility}
"""


# ═══════════════════════════════════════════════════════════════════
# PASS 2 — Decompose ONE functionality's modules into tasks/sub-tasks
# (run in parallel, one call per functionality → small focused outputs)
# ═══════════════════════════════════════════════════════════════════
PASS2_PROMPT = """
You are an Expert Project Manager doing detailed task breakdown.

You are given ONE functionality of a larger project, with its modules already identified.
Break EACH module into concrete engineering TASKS, and each task into SUB-TASKS.
Stay strictly within the scope of the provided modules — do NOT add new modules.

For EVERY task produce a row with:
  - no: "<ModuleNo>.<n>" e.g. module "A.1" → tasks "A.1.1", "A.1.2", ...
  - functionality: the functionality name (given below)
  - module: the parent module name (exactly as given)
  - task: short specific task name (e.g. "Build login API endpoint", "Login form UI")
  - sub_tasks: a list of 2-5 concrete sub-task strings (the granular steps of this task)
  - features: 1-2 sentences describing exactly what this task delivers. Be specific.
  - interface_type: technical layer(s), combinable with + (Web | Backend | AI Service | Cloud | Mobile | Data Pipeline | DevOps/CI-CD)
  - stack_involvement: for EVERY discipline in stack_columns, set true/false (at least one true)
  - estimated_hours: an integer representing total hours to build this task.
  - complexity: string rating ("Low", "Medium", or "High") based on technical risk.
  - is_mvp: true or false (if include_mvp is true, flag only essential tasks for the MVP. If false, flag everything as true)
  - tech_remarks: concrete assumption/design decision (name the technology, pattern, or constraint)
  - ba_remarks: ALWAYS ""

RULES:
- Decompose thoroughly: a typical module yields 2-5 tasks; each task yields 2-5 sub_tasks.
- "no" is ALWAYS a string like "A.1.2" — never a plain integer.
- stack_involvement MUST contain ALL of: {stack_columns_list}
- features is never empty.
- include_mvp flag for this generation is: {include_mvp_flag}
- HOURS ESTIMATE: Assume a Senior Full-Stack Developer is doing the work. Use lean estimates: 4-8 hours for simple APIs/UI, 16-24+ hours for complex AI/Cloud integrations. Measure in 4-hour increments.
- CRITICAL RULE: DO NOT invent features, modules, or systems (like booking/payments) that are not explicitly mentioned in the input context.
- Return ONLY valid JSON, no markdown, no prose.

OUTPUT FORMAT:
{{
  "items": [
    {{
      "no": "A.1.1",
      "functionality": "User Management & Authentication",
      "module": "Login Flow",
      "task": "Build login API endpoint",
      "sub_tasks": ["Validate email/password input", "Verify credentials against store", "Issue JWT access + refresh token", "Return rate-limited error on failure"],
      "features": "POST /login validates credentials and issues a 15-min JWT access token plus refresh token; repeated failures are rate limited.",
      "interface_type": "Backend",
      "stack_involvement": {{"Frontend": false, "Backend": true, "AI/ML": false, "DevOps": false, "Cloud": false}},
      "estimated_hours": 8,
      "complexity": "Medium",
      "is_mvp": true,
      "tech_remarks": "JWT 15min access + refresh rotation; 5 failed attempts → 15min lockout",
      "ba_remarks": ""
    }}
  ]
}}

stack_columns for this project: {stack_columns_list}

FUNCTIONALITY TO DECOMPOSE: {functionality_name}

MODULES IN THIS FUNCTIONALITY:
{modules_json}

PROJECT CONTEXT (for grounding tech choices — do not break these down):
{context}

Return ONLY the JSON object with the "items" array.
"""


# -----------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------
def _parse_items(raw_text: str) -> list:
    """Robustly pull the items[] list out of an LLM response, tolerating truncation."""
    try:
        parsed = extract_json(raw_text)
        if isinstance(parsed, dict) and parsed.get("items"):
            return parsed["items"]
    except Exception:
        pass
    return _recover_items(raw_text)


def _sort_key(no: str, func_order: dict) -> tuple:
    """Order rows by functionality letter, then numeric segments (A.1.2 → (0,1,2))."""
    parts = re.split(r"[.\-]", str(no).strip())
    letter = parts[0][:1].upper() if parts and parts[0] else "Z"
    nums = []
    for p in parts[1:]:
        m = re.search(r"\d+", p)
        nums.append(int(m.group()) if m else 0)
    return (func_order.get(letter, 999), *nums)


def _drop_incomplete(items: list) -> list:
    """Drop trailing item missing required fields (truncation artifact)."""
    if not items:
        return items
    last = items[-1]
    missing = [f for f in ("no", "functionality", "module", "task")
               if not str(last.get(f, "")).strip()]
    if missing:
        print(f"[EstimationAgent] Dropping incomplete last item (missing: {missing})")
        return items[:-1]
    return items


# -----------------------------------------------------------------
# Two-pass estimation
# -----------------------------------------------------------------
def run_estimation_agent(
    requirements: dict,
    plan: dict,
    feasibility: dict,
    transcript: str = "",
    include_mvp: bool = False,
    rag_context: str = "",
    feedback: str = "",
) -> EstimationAgentOutput:
    if not requirements or not plan or not feasibility:
        raise ValueError("Requirements, Plan, and Feasibility cannot be empty.")

    feedback_section = ""
    if feedback and feedback.strip():
        feedback_section = (
            f"USER FEEDBACK TO ADDRESS:\n---\n{feedback.strip()}\n---\n"
            "Incorporate this feedback before generating the output.\n"
        )
    if rag_context and rag_context.strip():
        feedback_section += f"\nADDITIONAL REFERENCE CONTEXT:\n{rag_context}\n"

    req_json = json.dumps(requirements, indent=2)
    plan_json = json.dumps(plan, indent=2)
    feas_json = json.dumps(feasibility, indent=2)

    # ── PASS 1: functionalities + modules ─────────────────────────────────────
    pass1_prompt = PASS1_PROMPT.format(
        requirements=req_json,
        plan=plan_json,
        feasibility=feas_json,
        feedback_section=feedback_section,
    )
    pass1_raw = generate_with_fallback(pass1_prompt, use_search=False, agent_name="estimation_agent")
    try:
        skeleton = extract_json(pass1_raw)
    except Exception as e:
        raise ValueError(
            f"Estimation Agent (Pass 1): could not parse functionality/module map.\n"
            f"First 400 chars:\n{pass1_raw[:400]}"
        ) from e

    stack_columns = skeleton.get("stack_columns") or []
    functionalities = skeleton.get("functionalities") or []
    modules = skeleton.get("modules") or []
    if not modules:
        raise ValueError("Estimation Agent (Pass 1): no modules were identified.")

    # Group modules by functionality name (preserving Pass-1 order)
    modules_by_func: dict[str, list] = {}
    for m in modules:
        fname = (m.get("functionality") or "").strip() or "Uncategorized"
        modules_by_func.setdefault(fname, []).append(m)

    stack_list_str = ", ".join(stack_columns) if stack_columns else "Backend"
    context = f"REQUIREMENTS:\n{req_json}\n\nARCHITECTURE PLAN:\n{plan_json}"[:6000]

    # ── PASS 2: decompose each functionality in parallel ──────────────────────
    def _decompose(fname: str, mods: list, max_retries: int = 3) -> list:
        prompt = PASS2_PROMPT.format(
            stack_columns_list=stack_list_str,
            functionality_name=fname,
            modules_json=json.dumps(mods, indent=2),
            context=context,
            include_mvp_flag="true" if include_mvp else "false",
        )
        for attempt in range(max_retries):
            try:
                raw = generate_with_fallback(prompt, use_search=False, agent_name="estimation_agent")
                items = _parse_items(raw)
                if items:
                    return items
                print(f"[EstimationAgent] Pass 2: '{fname}' returned no items (Attempt {attempt+1})")
            except Exception as e:
                print(f"[EstimationAgent] Pass 2 failed for '{fname}' (Attempt {attempt+1}): {e}")
            time.sleep(2)
        return []

    all_items: list = []
    with ThreadPoolExecutor(max_workers=min(len(modules_by_func), 5)) as ex:
        future_map = {ex.submit(_decompose, fn, mods): fn for fn, mods in modules_by_func.items()}
        for fut in as_completed(future_map):
            fname = future_map[fut]
            try:
                items = fut.result()
                if items:
                    all_items.extend(items)
                else:
                    print(f"[EstimationAgent] Pass 2: '{fname}' ultimately failed to generate items.")
            except Exception as e:
                print(f"[EstimationAgent] Pass 2 failed completely for '{fname}': {e}")

    if not all_items:
        raise ValueError("Estimation Agent (Pass 2): no tasks could be generated from any functionality.")

    all_items = _drop_incomplete(all_items)

    # Derive stack_columns from items if Pass 1 missed any
    if not stack_columns:
        stack_columns = list({
            k for it in all_items
            for k in (it.get("stack_involvement") or {}).keys()
        })

    # ── ASSEMBLE HIERARCHY ────────────────────────────────────────────────────
    # 1. Group tasks by module name
    tasks_by_module: dict[str, list] = {}
    for task_dict in all_items:
        mname = str(task_dict.get("module") or "").strip()
        tasks_by_module.setdefault(mname, []).append(EstimationTask(**task_dict))

    # 2. Build Functionality and Module objects
    nested_functionalities = []
    for func_dict in functionalities:
        func_name = (func_dict.get("name") or "").strip()
        func_modules = modules_by_func.get(func_name) or []
        
        nested_modules = []
        for m_dict in func_modules:
            mname = (m_dict.get("module") or "").strip()
            
            # Sort tasks by their `no` property
            module_tasks = tasks_by_module.get(mname) or []
            module_tasks.sort(key=lambda t: _sort_key(t.no, {}))
            
            nested_modules.append(EstimationModule(
                no=str(m_dict.get("no") or ""),
                module=mname,
                scope=str(m_dict.get("scope") or ""),
                tasks=module_tasks
            ))
            
        nested_functionalities.append(EstimationFunctionality(
            letter=str(func_dict.get("letter") or ""),
            name=func_name,
            modules=nested_modules
        ))

    return EstimationAgentOutput(
        stack_columns=stack_columns,
        functionalities=nested_functionalities,
        assumptions=skeleton.get("assumptions") or [],
    )

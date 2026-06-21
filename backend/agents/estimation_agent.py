import os
import json
from dotenv import load_dotenv
from backend.schemas.estimation_schema import EstimationAgentOutput
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


ESTIMATION_AGENT_PROMPT = """
You are an Expert Project Manager and Solution Architect.

Your job is to produce a complete, end-to-end Work Breakdown Structure (WBS) for the project described in the inputs below.

You will receive:
- Approved Requirements (from Task Agent)
- Approved Architecture Plan (from Planning Agent)
- Approved Feasibility Analysis (from Feasibility Agent)

These are your ONLY source of truth. Do NOT invent anything not present in the inputs.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 1 — IDENTIFY STACK DISCIPLINES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Read the Architecture Plan. Identify which discipline areas this project genuinely needs.

Choose ONLY from:
  Frontend | Backend | AI/ML | DevOps | Cloud | Mobile | Data Engineering | QA | Security

Output only disciplines that actually exist in THIS project's tech stack.
These become the dynamic column headers — output as:
  "stack_columns": ["Frontend", "Backend", "AI/ML", "DevOps"]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 2 — IDENTIFY FUNCTIONALITIES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Group the entire project into major functional areas. Label them A, B, C, D...

Example:
  A → User Management & Authentication
  B → AI Conversation Engine
  C → Reporting & Analytics
  D → Infrastructure & DevOps

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 3 — CREATE MODULES (ONE ROW PER MODULE)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

⚠️ CRITICAL RULE: ONE ROW PER MODULE. Never create multiple rows for the same module.

For each Functionality, list specific deliverable modules numbered A.0, A.1, A.2... B.1, B.2...

A module is ONE specific thing being built — not a layer, not a technology.

BAD (do NOT do this):
  Row 1: Authentication | Backend API
  Row 2: Authentication | Frontend UI
  Row 3: Authentication | Cloud Infrastructure
  ← WRONG: same module split into 3 rows by layer

GOOD (do this):
  Row 1: no=A.1 | module=Login Flow | features=User logs in via email/password, JWT issued on success, login form with validation | stack_involvement={{Frontend:true, Backend:true, Cloud:false}}
  ← CORRECT: one row, multiple disciplines marked true

For each module fill:
  - no: alphanumeric string like "A.1", "B.3" (NEVER a plain integer like 1, 2, 3)
  - functionality: the parent functionality name
  - module: short specific name (e.g. "Login Flow", "JWT Token Management", "RAG Pipeline", "Role-Based Access Control")
  - features: 1-2 sentences describing EXACTLY what gets built in this module. Be specific.
    Example: "User authenticates via email and password. On success, a JWT access token (15 min) and refresh token are issued. Invalid credential errors handled with rate limiting."
    Example: "Documents uploaded by managers are chunked into 512-token segments, embedded using Gemini embedding-001, and stored in pgvector with HNSW index for fast similarity search."

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 4 — ASSIGN INTERFACE TYPE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

For each module, write the Interface Type — the technical layer(s) it spans.
Can be combined with +: Web | Backend | AI Service | Cloud | Mobile | Data Pipeline | DevOps/CI-CD
Example: "Web + Backend", "Backend + AI Service", "Backend + Cloud"

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 5 — MARK STACK INVOLVEMENT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

For each module, for EVERY discipline in stack_columns, set true or false.

⚠️ RULES:
- stack_involvement MUST include ALL disciplines from stack_columns — no missing keys
- true = this discipline does real work on this module
- false = this discipline is not involved
- At least ONE discipline must be true per module
- Multiple disciplines can be true for the same module — this is the point

Example for "Login Flow" (stack_columns = ["Frontend","Backend","AI/ML","DevOps","Cloud"]):
  stack_involvement: {{"Frontend": true, "Backend": true, "AI/ML": false, "DevOps": false, "Cloud": false}}

Example for "CI/CD Pipeline Setup":
  stack_involvement: {{"Frontend": false, "Backend": false, "AI/ML": false, "DevOps": true, "Cloud": true}}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 6 — TECH REMARKS & BA REMARKS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

- tech_remarks: specific assumptions or design decisions for this module.
  Be concrete — name the technology, pattern, or constraint.
  E.g. "JWT access token 15min expiry + refresh token rotation; Redis for token blacklist"
  E.g. "Gemini embedding-001 (768-dim) + pgvector HNSW index; top-k=6 retrieval"
  E.g. "ElevenLabs TTS API; voice assigned per persona; fallback to browser speech synthesis"

- ba_remarks: ALWAYS "" — left blank for BA team to fill manually

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 7 — COMPLETENESS CHECK
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

✅ Every requirement covered by at least one module
✅ Every architecture component has a module
✅ Every discipline in stack_columns is marked true in at least one module
✅ No module has all disciplines false
✅ features field is filled with a specific description for every module — never empty
✅ no field is always a string like "A.1" — never an integer
✅ Infrastructure, Security, Testing, CI/CD all covered
✅ Coverage end-to-end: DB → API → UI → AI → Cloud → Security → QA → DevOps

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 8 — OUTPUT FORMAT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Return ONLY valid JSON. No markdown, no extra text, no explanations.

{{
  "functionalities": [
    {{"letter": "A", "name": "User Management & Authentication"}},
    {{"letter": "B", "name": "AI Conversation Engine"}},
    {{"letter": "C", "name": "Infrastructure & DevOps"}}
  ],
  "stack_columns": ["Frontend", "Backend", "AI/ML", "DevOps", "Cloud"],
  "items": [
    {{
      "no": "A.0",
      "functionality": "User Management & Authentication",
      "module": "Auth Setup & Configuration",
      "features": "Supabase Auth configured with email/password provider. Base routing, middleware, and environment setup for the full authentication system.",
      "interface_type": "Backend + DevOps",
      "stack_involvement": {{
        "Frontend": true,
        "Backend": true,
        "AI/ML": false,
        "DevOps": true,
        "Cloud": false
      }},
      "tech_remarks": "Supabase Auth with RLS enabled; .env managed via dotenv; CORS configured for frontend origin",
      "ba_remarks": ""
    }},
    {{
      "no": "A.1",
      "functionality": "User Management & Authentication",
      "module": "Login Flow",
      "features": "User authenticates via email and password. JWT access token (15 min) and refresh token issued on success. Invalid credential errors returned with rate limiting on repeated failures.",
      "interface_type": "Web + Backend",
      "stack_involvement": {{
        "Frontend": true,
        "Backend": true,
        "AI/ML": false,
        "DevOps": false,
        "Cloud": false
      }},
      "tech_remarks": "JWT access token 15min; refresh token rotation on use; 5 failed attempts triggers 15min lockout",
      "ba_remarks": ""
    }},
    {{
      "no": "A.2",
      "functionality": "User Management & Authentication",
      "module": "Role-Based Access Control",
      "features": "Three roles: Associate, Manager, Admin. Role assigned at registration. API middleware enforces role permissions on all protected routes. Frontend conditionally renders UI based on role.",
      "interface_type": "Web + Backend",
      "stack_involvement": {{
        "Frontend": true,
        "Backend": true,
        "AI/ML": false,
        "DevOps": false,
        "Cloud": false
      }},
      "tech_remarks": "RBAC middleware applied at route level; roles stored in Supabase user metadata; frontend reads role from JWT claims",
      "ba_remarks": ""
    }},
    {{
      "no": "B.1",
      "functionality": "AI Conversation Engine",
      "module": "RAG Pipeline",
      "features": "Uploaded documents chunked into 512-token segments, embedded via Gemini embedding-001 (768-dim), and stored in pgvector with HNSW index. Similarity search retrieves top-6 chunks per query.",
      "interface_type": "Backend + AI Service",
      "stack_involvement": {{
        "Frontend": false,
        "Backend": true,
        "AI/ML": true,
        "DevOps": false,
        "Cloud": false
      }},
      "tech_remarks": "Gemini embedding-001; 768-dim vectors; pgvector HNSW index; cosine similarity; top-k=6 retrieval",
      "ba_remarks": ""
    }}
  ],
  "assumptions": [
    "Supabase used for auth, database, and vector storage",
    "Gemini 2.0 Flash used as primary LLM with OpenRouter fallback"
  ]
}}

STRICT RULES — READ CAREFULLY:
1. "no" is ALWAYS a string: "A.1", "B.3" — NEVER an integer like 1, 2, 3
2. ONE ROW PER MODULE — never split one module into multiple rows by layer/discipline
3. "features" MUST be filled for every row — a specific 1-2 sentence description, never empty
4. stack_involvement MUST have ALL disciplines from stack_columns as keys (true or false)
5. At least one discipline must be true per module
6. "ba_remarks" is always "" — never fill it
7. Return ONLY valid JSON

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

    prompt = ESTIMATION_AGENT_PROMPT.format(
        requirements=json.dumps(requirements, indent=2),
        plan=json.dumps(plan, indent=2),
        feasibility=json.dumps(feasibility, indent=2),
        feedback_section=feedback_section,
    )

    raw_text = generate_with_fallback(prompt, use_search=False, agent_name="estimation_agent")

    # Stage 1: full JSON extraction
    parsed = None
    try:
        parsed = extract_json(raw_text)
    except Exception as e:
        print(f"[EstimationAgent] extract_json failed ({e}), trying item-by-item recovery")

    # Stage 2: item-by-item recovery for truncated output
    if not parsed or not parsed.get("items"):
        recovered = _recover_items(raw_text)
        if recovered:
            print(f"[EstimationAgent] Recovered {len(recovered)} items from truncated output")
            stack_cols = list({
                k for item in recovered
                for k in (item.get("stack_involvement") or {}).keys()
            })
            parsed = {
                "functionalities": [],
                "stack_columns": stack_cols,
                "items": recovered,
                "assumptions": [],
            }
        else:
            raise ValueError(
                f"Estimation Agent: could not extract any items from LLM output.\n"
                f"First 400 chars:\n{raw_text[:400]}"
            )

    # Drop incomplete last item (missing required fields)
    items = parsed.get("items", [])
    if items:
        last = items[-1]
        missing = [f for f in ("no", "functionality", "module", "features", "interface_type")
                   if not str(last.get(f, "")).strip()]
        if missing:
            print(f"[EstimationAgent] Dropping incomplete last item (missing: {missing})")
            parsed["items"] = items[:-1]

    # Derive stack_columns from items if agent forgot to include them
    if not parsed.get("stack_columns") and parsed.get("items"):
        parsed["stack_columns"] = list({
            k for item in parsed["items"]
            for k in (item.get("stack_involvement") or {}).keys()
        })

    return EstimationAgentOutput(**parsed)

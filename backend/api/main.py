import sys
from pathlib import Path

root_dir = Path(__file__).resolve().parent.parent.parent
if str(root_dir) not in sys.path:
    sys.path.append(str(root_dir))

from fastapi import FastAPI, UploadFile, File, HTTPException, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional

app = FastAPI(title="Agent Architect API", version="1.0.0")

# ... existing code ...

app = FastAPI(title="Agent Architect API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Request models ────────────────────────────────────────────────

class TaskAgentRequest(BaseModel):
    transcript: str
    feedback: Optional[str] = ""

class PlanningAgentRequest(BaseModel):
    requirements: dict
    project_id: Optional[str] = None
    feedback: Optional[str] = ""

class FeasibilityAgentRequest(BaseModel):
    requirements: dict
    plan: dict
    feedback: Optional[str] = ""

class EstimationAgentRequest(BaseModel):
    requirements: dict
    plan: dict
    feasibility: dict
    transcript: Optional[str] = ""
    include_mvp: Optional[bool] = False
    project_id: Optional[str] = None
    feedback: Optional[str] = ""

class ReportAgentRequest(BaseModel):
    requirements: dict
    plan: dict
    feasibility: dict
    estimation: dict

class DeleteDocRequest(BaseModel):
    document_name: Optional[str] = None


# ── RAG helper ────────────────────────────────────────────────────

def _build_rag_context(project_id: Optional[str], requirements: dict) -> str:
    if not project_id:
        return ""
    from backend.rag.retrival import retrieve_context, format_context_for_prompt
    query = " ".join(
        requirements.get("pain_points", []) +
        requirements.get("requirements", []) +
        requirements.get("business_goals", [])
    )[:1500]
    chunks = retrieve_context(project_id, query)
    return format_context_for_prompt(chunks)


def _is_quota_error(error_msg: str) -> bool:
    """Check if error message indicates API quota/rate limit."""
    keywords = ["429", "too many requests", "quota", "rate limit", "limit exceeded", "resource exhausted"]
    return any(kw in error_msg.lower() for kw in keywords)


# ── Agent endpoints ───────────────────────────────────────────────

@app.post("/api/task-agent")
def task_agent(req: TaskAgentRequest):
    from backend.agents.task_agent import run_task_agent
    try:
        result = run_task_agent(req.transcript, feedback=req.feedback or "")
        return result.model_dump()
    except ValueError as ve:
        if _is_quota_error(str(ve)):
            raise HTTPException(status_code=503, detail=f"API quota exhausted. Please wait a few minutes and try again. Details: {str(ve)[:500]}")
        raise HTTPException(status_code=422, detail=str(ve)[:2000])
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {str(e)[:1000]}")


@app.post("/api/planning-agent")
def planning_agent(req: PlanningAgentRequest):
    from backend.agents.planning_agent import run_planning_agent
    try:
        rag_context = _build_rag_context(req.project_id, req.requirements)
        result = run_planning_agent(req.requirements, rag_context=rag_context, feedback=req.feedback or "")
        return result.model_dump()
    except ValueError as ve:
        if _is_quota_error(str(ve)):
            raise HTTPException(status_code=503, detail=f"API quota exhausted. Please wait a few minutes and try again. Details: {str(ve)[:500]}")
        raise HTTPException(status_code=422, detail=str(ve)[:2000])
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {str(e)[:1000]}")


@app.post("/api/feasibility-agent")
def feasibility_agent(req: FeasibilityAgentRequest):
    from backend.agents.feasibility_agent import run_feasibility_agent
    try:
        result = run_feasibility_agent(req.requirements, req.plan, feedback=req.feedback or "")
        return result.model_dump()
    except ValueError as ve:
        if _is_quota_error(str(ve)):
            raise HTTPException(status_code=503, detail=f"API quota exhausted. Please wait a few minutes and try again. Details: {str(ve)[:500]}")
        raise HTTPException(status_code=422, detail=str(ve)[:2000])
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {str(e)[:1000]}")


@app.post("/api/estimation-agent")
def estimation_agent(req: EstimationAgentRequest):
    from backend.agents.estimation_agent import run_estimation_agent
    try:
        rag_context = _build_rag_context(req.project_id, req.requirements)
        result = run_estimation_agent(
            req.requirements, req.plan, req.feasibility,
            transcript=req.transcript or "",
            include_mvp=req.include_mvp or False,
            rag_context=rag_context,
            feedback=req.feedback or "",
        )
        return result.model_dump()
    except ValueError as ve:
        if _is_quota_error(str(ve)):
            raise HTTPException(status_code=503, detail=f"API quota exhausted. Please wait a few minutes and try again. Details: {str(ve)[:500]}")
        raise HTTPException(status_code=422, detail=str(ve)[:2000])
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {str(e)[:1000]}")


@app.post("/api/report-agent")
def report_agent(req: ReportAgentRequest):
    from backend.agents.report_agent import run_report_agent
    try:
        result = run_report_agent(req.requirements, req.plan, req.feasibility, req.estimation)
        return result.model_dump()
    except ValueError as ve:
        if _is_quota_error(str(ve)):
            raise HTTPException(status_code=503, detail=f"API quota exhausted. Please wait a few minutes and try again. Details: {str(ve)[:500]}")
        raise HTTPException(status_code=422, detail=str(ve)[:2000])
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {str(e)[:1000]}")


# ── RAG endpoints ─────────────────────────────────────────────────

@app.post("/api/rag/{project_id}/ingest")
async def ingest(project_id: str, file: UploadFile = File(...)):
    from backend.rag.ingestion import ingest_document
    try:
        file_bytes = await file.read()
        file_type = (file.filename or "").rsplit(".", 1)[-1].lower()
        return ingest_document(project_id, file_bytes, file.filename or "upload", file_type)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/rag/{project_id}/documents")
def list_documents(project_id: str):
    from backend.rag.ingestion import list_project_documents
    return list_project_documents(project_id)


@app.delete("/api/rag/{project_id}/documents")
def delete_document(project_id: str, req: DeleteDocRequest = Body(default=DeleteDocRequest())):
    from backend.rag.ingestion import delete_project_documents
    return delete_project_documents(project_id, req.document_name)


@app.get("/health")
def health():
    return {"status": "ok"}
@app.api_route("/api/{path:path}", methods=["GET", "PUT", "PATCH"])
async def api_method_not_allowed(path: str):
    return JSONResponse(
        status_code=405,
        content={
            "error": "Method Not Allowed",
            "hint": f"The endpoint '/api/{path}' only accepts POST requests.",
            "message": "Please use the Streamlit frontend at http://localhost:8501 to interact with the app.",
        },
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.api.main:app", host="0.0.0.0", port=8000, reload=True)

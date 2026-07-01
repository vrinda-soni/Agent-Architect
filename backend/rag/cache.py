"""
Semantic Q&A cache backed by Supabase pgvector.
On a cache hit (similarity >= threshold), the stored answer is returned immediately
without running the RAG pipeline or calling the LLM.
"""

import time

_SIMILARITY_THRESHOLD = 0.92
_LOCAL_CACHE: dict[str, list[dict]] = {}   # project_id → [{embedding, question, answer, ts}]
_LOCAL_TTL   = 600                          # 10-min in-memory TTL to avoid redundant DB reads


def _supabase():
    from backend.supabase import supabase
    return supabase


def _embed(text: str) -> list[float]:
    from backend.rag.retrival import _embed as _rag_embed
    return _rag_embed(text)


def search_cache(project_id: str, question: str, threshold: float = _SIMILARITY_THRESHOLD) -> str | None:
    """
    Embed `question` and look for a semantically similar past answer.
    Returns the cached answer string if found, else None.
    """
    sb = _supabase()
    if not sb:
        return None
    try:
        embedding = _embed(question)
        resp = sb.rpc("match_qa_cache", {
            "query_embedding": embedding,
            "filter_project_id": project_id,
            "match_threshold": threshold,
            "match_count": 1,
        }).execute()
        rows = resp.data or []
        if rows:
            print(f"[SemanticCache] HIT — similarity {rows[0].get('similarity', '?'):.3f} for: {question[:60]}")
            return rows[0]["answer_text"]
    except Exception as e:
        print(f"[SemanticCache] search error: {e}")
    return None


def store_cache(project_id: str, question: str, answer: str) -> None:
    """Embed `question` and store the Q&A pair for future cache hits."""
    sb = _supabase()
    if not sb:
        return
    try:
        embedding = _embed(question)
        sb.table("qa_cache").insert({
            "project_id": project_id,
            "question_text": question,
            "question_embedding": embedding,
            "answer_text": answer,
        }).execute()
        print(f"[SemanticCache] Stored: {question[:60]}")
    except Exception as e:
        print(f"[SemanticCache] store error: {e}")

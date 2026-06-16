import os
import time
from dotenv import load_dotenv

load_dotenv()

# ── In-memory caches ──────────────────────────────────────────────────────────
_embed_cache: dict[str, list[float]] = {}          # text → vector
_retrieval_cache: dict[tuple, tuple] = {}          # (project_id, query) → (chunks, ts)
_RETRIEVAL_TTL = 300                               # 5 min TTL for retrieval cache


def _supabase():
    from backend.supabase import supabase
    return supabase


def _embed_gemini(text: str) -> list[float]:
    from google import genai
    from google.genai.types import EmbedContentConfig
    client = genai.Client(api_key=os.getenv("GEMINI_API_KEY", ""))
    result = client.models.embed_content(
        model="models/gemini-embedding-001",
        contents=text,
        config=EmbedContentConfig(output_dimensionality=768),  # match Supabase pgvector dim
    )
    return [float(v) for v in result.embeddings[0].values]


def _embed_hf_bge(text: str) -> list[float]:
    # Fallback: BAAI/bge-m3 via HF Inference API (1024-dim, truncated to 768)
    from huggingface_hub import InferenceClient
    client = InferenceClient(token=os.getenv("HF_TOKEN", ""))
    result = client.feature_extraction(text, model="BAAI/bge-m3")
    embedding = result[0] if hasattr(result[0], "__iter__") else result
    return [float(v) for v in embedding[:768]]  # native floats for JSON serialization


def _embed(text: str) -> list[float]:
    # Check embedding cache first
    if text in _embed_cache:
        return _embed_cache[text]
    try:
        vec = _embed_gemini(text)
    except Exception as e:
        print(f"[RAG] Gemini embed failed, falling back to BAAI/bge-m3: {e}")
        vec = _embed_hf_bge(text)
    _embed_cache[text] = vec
    return vec


def retrieve_context(project_id: str, query_text: str, top_k: int = 5) -> list[dict]:
    if not project_id or not query_text.strip():
        return []
    sb = _supabase()
    if not sb:
        return []

    # Check retrieval cache (project_id + query key)
    cache_key = (project_id, query_text.strip()[:500])
    if cache_key in _retrieval_cache:
        chunks, ts = _retrieval_cache[cache_key]
        if time.time() - ts < _RETRIEVAL_TTL:
            return chunks

    try:
        query_embedding = _embed(query_text[:2000])
        resp = sb.rpc("match_document_chunks", {
            "query_embedding": query_embedding,
            "filter_project_id": project_id,
            "match_count": top_k,
        }).execute()
        chunks = resp.data or []
        _retrieval_cache[cache_key] = (chunks, time.time())
        return chunks
    except Exception as e:
        print(f"[RAG] retrieval error: {e}")
        return []


def format_context_for_prompt(chunks: list[dict]) -> str:
    if not chunks:
        return ""
    lines = ["[REFERENCE CONTEXT FROM PROJECT DOCUMENTS]"]
    for i, chunk in enumerate(chunks, 1):
        lines.append(f"\n--- Source: {chunk.get('document_name', 'Unknown')} (chunk {i}) ---")
        lines.append(chunk.get("chunk_text", ""))
    lines.append("\n[END OF REFERENCE CONTEXT]")
    return "\n".join(lines)

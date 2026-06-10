import os
from dotenv import load_dotenv

load_dotenv()


def _supabase():
    from backend.supabase import supabase
    return supabase


def _embed_gemini(text: str) -> list[float]:
    from google import genai
    client = genai.Client(api_key=os.getenv("GEMINI_API_KEY", ""))
    result = client.models.embed_content(
        model="text-embedding-004",
        contents=text,
    )
    return result.embeddings[0].values  # 768-dim


def _embed_hf_bge(text: str) -> list[float]:
    # Fallback: BAAI/bge-m3 via HF Inference API (1024-dim, truncated to 768)
    from huggingface_hub import InferenceClient
    client = InferenceClient(token=os.getenv("HF_TOKEN", ""))
    result = client.feature_extraction(text, model="BAAI/bge-m3")
    embedding = result[0] if hasattr(result[0], "__iter__") else result
    return list(embedding)[:768]


def _embed(text: str) -> list[float]:
    try:
        return _embed_gemini(text)
    except Exception as e:
        print(f"[RAG] Gemini embed failed, falling back to BAAI/bge-m3: {e}")
        return _embed_hf_bge(text)


def retrieve_context(project_id: str, query_text: str, top_k: int = 5) -> list[dict]:
    if not project_id or not query_text.strip():
        return []
    sb = _supabase()
    if not sb:
        return []
    try:
        query_embedding = _embed(query_text[:2000])
        resp = sb.rpc("match_document_chunks", {
            "query_embedding": query_embedding,
            "filter_project_id": project_id,
            "match_count": top_k,
        }).execute()
        return resp.data or []
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

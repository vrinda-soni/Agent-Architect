import os
import io
from typing import Optional
from dotenv import load_dotenv

load_dotenv()

CHUNK_SIZE = 600
CHUNK_OVERLAP = 100


def _supabase():
    from backend.supabase import supabase
    return supabase


def _gemini_client():
    from google import genai
    return genai.Client(api_key=os.getenv("GEMINI_API_KEY", ""))


def extract_text(file_bytes: bytes, file_type: str) -> str:
    if file_type == "pdf":
        import PyPDF2
        reader = PyPDF2.PdfReader(io.BytesIO(file_bytes))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    elif file_type == "docx":
        import docx
        doc = docx.Document(io.BytesIO(file_bytes))
        return "\n".join(p.text for p in doc.paragraphs if p.text.strip())
    elif file_type == "doc":
        # .doc is old binary Word format — try python-docx first, fall back to text extraction
        try:
            import docx
            doc = docx.Document(io.BytesIO(file_bytes))
            return "\n".join(p.text for p in doc.paragraphs if p.text.strip())
        except Exception:
            # Binary extraction: pull printable ASCII sequences (crude but works for most .doc files)
            import re
            raw = file_bytes.decode("latin-1", errors="ignore")
            chunks = re.findall(r'[\x20-\x7e\n\r\t]{4,}', raw)
            return "\n".join(line.strip() for line in chunks if line.strip())
    else:
        return file_bytes.decode("utf-8", errors="ignore")


def chunk_text(text: str) -> list[str]:
    text = text.strip()
    if not text:
        return []
    chunks = []
    start = 0
    while start < len(text):
        end = min(start + CHUNK_SIZE, len(text))
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        start = end - CHUNK_OVERLAP
    return chunks


def _embed_gemini(text: str) -> list[float]:
    client = _gemini_client()
    result = client.models.embed_content(
        model="models/text-embedding-004",
        contents=text,
    )
    # Convert to native Python floats for JSON serialization
    return [float(v) for v in result.embeddings[0].values]  # 768-dim


def _embed_hf_bge(text: str) -> list[float]:
    # Fallback: BAAI/bge-m3 via HF Inference API (1024-dim, truncated to 768)
    from huggingface_hub import InferenceClient
    client = InferenceClient(token=os.getenv("HF_TOKEN", ""))
    result = client.feature_extraction(text, model="BAAI/bge-m3")
    # result may be nested list or 2-D array — flatten to 1-D
    embedding = result[0] if hasattr(result[0], "__iter__") else result
    # Convert to native Python floats for JSON serialization
    return [float(v) for v in embedding[:768]]


def _embed(text: str) -> list[float]:
    try:
        return _embed_gemini(text)
    except Exception as e:
        print(f"[RAG] Gemini embed failed, falling back to BAAI/bge-m3: {e}")
        return _embed_hf_bge(text)


def ingest_document(
    project_id: str,
    file_bytes: bytes,
    file_name: str,
    file_type: str,
) -> dict:
    sb = _supabase()
    if not sb:
        return {"success": False, "error": "Supabase not initialized"}

    # Replace any existing chunks for this document
    sb.table("document_chunks") \
        .delete() \
        .eq("project_id", project_id) \
        .eq("document_name", file_name) \
        .execute()

    text = extract_text(file_bytes, file_type)
    if not text.strip():
        return {"success": False, "error": "No text could be extracted from the document"}

    chunks = chunk_text(text)
    if not chunks:
        return {"success": False, "error": "No chunks generated"}

    records = []
    for i, chunk in enumerate(chunks):
        try:
            embedding = _embed(chunk)
            records.append({
                "project_id": project_id,
                "document_name": file_name,
                "document_type": file_type,
                "chunk_text": chunk,
                "chunk_index": i,
                "embedding": embedding,
            })
        except Exception as e:
            print(f"[RAG] embed chunk {i} failed: {e}")
            continue

    if not records:
        return {"success": False, "error": "Embedding failed for all chunks"}

    batch_size = 25
    for i in range(0, len(records), batch_size):
        sb.table("document_chunks").insert(records[i:i + batch_size]).execute()

    return {"success": True, "chunks_inserted": len(records), "document_name": file_name}


def delete_project_documents(
    project_id: str,
    document_name: Optional[str] = None,
) -> dict:
    sb = _supabase()
    if not sb:
        return {"success": False, "error": "Supabase not initialized"}
    q = sb.table("document_chunks").delete().eq("project_id", project_id)
    if document_name:
        q = q.eq("document_name", document_name)
    q.execute()
    return {"success": True}


def list_project_documents(project_id: str) -> list[dict]:
    sb = _supabase()
    if not sb:
        return []
    resp = sb.table("document_chunks") \
        .select("document_name, document_type") \
        .eq("project_id", project_id) \
        .execute()
    seen: set[str] = set()
    docs = []
    for row in (resp.data or []):
        name = row["document_name"]
        if name not in seen:
            seen.add(name)
            docs.append({"document_name": name, "document_type": row["document_type"]})
    return docs

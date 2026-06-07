-- ============================================================
-- RAG Migration: Run this ONCE in the Supabase SQL Editor
-- Dashboard → SQL Editor → New Query → Paste → Run
-- ============================================================

-- Step 1: Enable pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- Step 2: Create document_chunks table
CREATE TABLE IF NOT EXISTS document_chunks (
    id           UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    project_id   UUID NOT NULL,
    document_name TEXT NOT NULL,
    document_type TEXT NOT NULL,
    chunk_text   TEXT NOT NULL,
    chunk_index  INTEGER NOT NULL DEFAULT 0,
    embedding    vector(768),
    created_at   TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Step 3: Disable RLS (POC — enable with user-scoped policies for production)
ALTER TABLE document_chunks DISABLE ROW LEVEL SECURITY;

-- Step 4: Index on project_id for fast per-project filtering
CREATE INDEX IF NOT EXISTS idx_document_chunks_project_id
    ON document_chunks (project_id);

-- Step 5: HNSW vector index for fast cosine similarity search
CREATE INDEX IF NOT EXISTS idx_document_chunks_embedding_hnsw
    ON document_chunks
    USING hnsw (embedding vector_cosine_ops);

-- Step 6: Similarity search function (called via supabase.rpc)
CREATE OR REPLACE FUNCTION match_document_chunks(
    query_embedding  vector(768),
    filter_project_id TEXT,
    match_count      INT DEFAULT 5
)
RETURNS TABLE (
    id            UUID,
    chunk_text    TEXT,
    document_name TEXT,
    document_type TEXT,
    similarity    FLOAT
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
    RETURN QUERY
    SELECT
        dc.id,
        dc.chunk_text,
        dc.document_name,
        dc.document_type,
        1 - (dc.embedding <=> query_embedding) AS similarity
    FROM document_chunks dc
    WHERE dc.project_id = filter_project_id::UUID
    ORDER BY dc.embedding <=> query_embedding
    LIMIT match_count;
END;
$$;

-- ============================================================
-- Semantic Q&A Cache Migration
-- Run ONCE in Supabase: Dashboard → SQL Editor → New Query → Paste → Run
-- ============================================================

CREATE TABLE IF NOT EXISTS qa_cache (
    id                 UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    project_id         UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    question_text      TEXT NOT NULL,
    question_embedding vector(768),
    answer_text        TEXT NOT NULL,
    created_at         TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

ALTER TABLE qa_cache DISABLE ROW LEVEL SECURITY;

CREATE INDEX IF NOT EXISTS idx_qa_cache_project_id ON qa_cache (project_id);
CREATE INDEX IF NOT EXISTS idx_qa_cache_embedding_hnsw
    ON qa_cache USING hnsw (question_embedding vector_cosine_ops);

-- Similarity search function used by cache.py
CREATE OR REPLACE FUNCTION match_qa_cache(
    query_embedding   vector(768),
    filter_project_id TEXT,
    match_threshold   FLOAT DEFAULT 0.92,
    match_count       INT   DEFAULT 1
)
RETURNS TABLE (
    id            UUID,
    question_text TEXT,
    answer_text   TEXT,
    similarity    FLOAT
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
    RETURN QUERY
    SELECT
        qc.id,
        qc.question_text,
        qc.answer_text,
        1 - (qc.question_embedding <=> query_embedding) AS similarity
    FROM qa_cache qc
    WHERE qc.project_id = filter_project_id::UUID
      AND 1 - (qc.question_embedding <=> query_embedding) >= match_threshold
    ORDER BY qc.question_embedding <=> query_embedding
    LIMIT match_count;
END;
$$;

-- ============================================================
-- Pipeline Runs Migration
-- Run ONCE in Supabase: Dashboard → SQL Editor → New Query → Paste → Run
-- ============================================================

CREATE TABLE IF NOT EXISTS pipeline_runs (
    project_id          UUID PRIMARY KEY REFERENCES projects(id) ON DELETE CASCADE,
    task_output         JSONB,
    approved_requirements JSONB,
    plan_output         JSONB,
    feasibility_output  JSONB,
    estimation_output   JSONB,
    approved_estimation JSONB,
    updated_at          TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

ALTER TABLE pipeline_runs DISABLE ROW LEVEL SECURITY;

CREATE INDEX IF NOT EXISTS idx_pipeline_runs_project_id ON pipeline_runs (project_id);

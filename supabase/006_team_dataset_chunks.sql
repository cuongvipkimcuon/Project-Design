-- Chia payload lớn thành chunk (gzip) — tránh timeout PostgREST

ALTER TABLE public.team_datasets
    ALTER COLUMN rows_data SET DEFAULT '[]'::jsonb;

ALTER TABLE public.team_datasets
    ADD COLUMN IF NOT EXISTS storage_format TEXT NOT NULL DEFAULT 'inline'
        CHECK (storage_format IN ('inline', 'chunked'));

CREATE TABLE IF NOT EXISTS public.team_dataset_chunks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    dataset_id UUID NOT NULL REFERENCES public.team_datasets(id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    row_count INTEGER NOT NULL DEFAULT 0,
    payload_gzip BYTEA NOT NULL,
    UNIQUE (dataset_id, chunk_index)
);

CREATE INDEX IF NOT EXISTS idx_team_chunks_dataset ON public.team_dataset_chunks(dataset_id);

ALTER TABLE public.team_dataset_chunks ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS team_chunks_select ON public.team_dataset_chunks;
CREATE POLICY team_chunks_select ON public.team_dataset_chunks
    FOR SELECT TO authenticated
    USING (true);

DROP POLICY IF EXISTS team_chunks_admin_write ON public.team_dataset_chunks;
CREATE POLICY team_chunks_admin_write ON public.team_dataset_chunks
    FOR ALL TO authenticated
    USING (public.is_admin())
    WITH CHECK (public.is_admin());

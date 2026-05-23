-- Plan / phiếu / tồn NPL — đồng bộ team realtime (snapshot gzip)

CREATE TABLE IF NOT EXISTS public.team_ops_sync (
    id TEXT PRIMARY KEY DEFAULT 'default',
    version BIGINT NOT NULL DEFAULT 0,
    content_hash TEXT NOT NULL DEFAULT '',
    payload_gzip BYTEA NOT NULL DEFAULT '\x'::bytea,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_by UUID REFERENCES public.profiles(id) ON DELETE SET NULL,
    updated_by_name TEXT NOT NULL DEFAULT ''
);

ALTER TABLE public.team_ops_sync ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS team_ops_sync_select ON public.team_ops_sync;
CREATE POLICY team_ops_sync_select ON public.team_ops_sync
    FOR SELECT TO authenticated
    USING (true);

DROP POLICY IF EXISTS team_ops_sync_insert ON public.team_ops_sync;
CREATE POLICY team_ops_sync_insert ON public.team_ops_sync
    FOR INSERT TO authenticated
    WITH CHECK (true);

DROP POLICY IF EXISTS team_ops_sync_update ON public.team_ops_sync;
CREATE POLICY team_ops_sync_update ON public.team_ops_sync
    FOR UPDATE TO authenticated
    USING (true)
    WITH CHECK (true);

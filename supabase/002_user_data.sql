-- Settings + dataset metadata per user (idempotent)

CREATE TABLE IF NOT EXISTS public.user_settings (
    owner_id UUID NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
    key TEXT NOT NULL,
    value TEXT NOT NULL DEFAULT '',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (owner_id, key)
);

CREATE TABLE IF NOT EXISTS public.user_datasets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id UUID NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
    dataset_type TEXT NOT NULL CHECK (dataset_type IN ('ol', 'bom_ke')),
    file_name TEXT NOT NULL DEFAULT '',
    file_path TEXT NOT NULL DEFAULT '',
    file_hash TEXT NOT NULL DEFAULT '',
    content_hash TEXT NOT NULL DEFAULT '',
    row_count INTEGER NOT NULL DEFAULT 0,
    imported_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    is_active BOOLEAN NOT NULL DEFAULT FALSE,
    visibility TEXT NOT NULL DEFAULT 'private' CHECK (visibility IN ('private', 'team')),
    UNIQUE (owner_id, dataset_type, content_hash)
);

CREATE INDEX IF NOT EXISTS idx_user_datasets_owner ON public.user_datasets(owner_id);
CREATE INDEX IF NOT EXISTS idx_user_datasets_active ON public.user_datasets(owner_id, dataset_type, is_active);
CREATE INDEX IF NOT EXISTS idx_user_datasets_visibility ON public.user_datasets(visibility);

ALTER TABLE public.user_settings ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.user_datasets ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS user_settings_own ON public.user_settings;
CREATE POLICY user_settings_own ON public.user_settings
    FOR ALL TO authenticated
    USING (owner_id = auth.uid())
    WITH CHECK (owner_id = auth.uid());

DROP POLICY IF EXISTS user_datasets_select ON public.user_datasets;
CREATE POLICY user_datasets_select ON public.user_datasets
    FOR SELECT TO authenticated
    USING (
        owner_id = auth.uid()
        OR visibility = 'team'
    );

DROP POLICY IF EXISTS user_datasets_write ON public.user_datasets;
CREATE POLICY user_datasets_write ON public.user_datasets
    FOR INSERT TO authenticated
    WITH CHECK (owner_id = auth.uid());

DROP POLICY IF EXISTS user_datasets_update_own ON public.user_datasets;
CREATE POLICY user_datasets_update_own ON public.user_datasets
    FOR UPDATE TO authenticated
    USING (owner_id = auth.uid())
    WITH CHECK (owner_id = auth.uid());

DROP POLICY IF EXISTS user_datasets_delete_own ON public.user_datasets;
CREATE POLICY user_datasets_delete_own ON public.user_datasets
    FOR DELETE TO authenticated
    USING (owner_id = auth.uid());

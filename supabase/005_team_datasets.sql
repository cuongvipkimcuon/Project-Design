-- Dữ liệu OL / bảng kê admin chia sẻ — user khác tải về không cần đọc Excel

CREATE TABLE IF NOT EXISTS public.team_datasets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    dataset_type TEXT NOT NULL CHECK (dataset_type IN ('ol', 'bom_ke')),
    publisher_id UUID NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
    publisher_name TEXT NOT NULL DEFAULT '',
    file_name TEXT NOT NULL DEFAULT '',
    file_path TEXT NOT NULL DEFAULT '',
    file_hash TEXT NOT NULL DEFAULT '',
    content_hash TEXT NOT NULL DEFAULT '',
    row_count INTEGER NOT NULL DEFAULT 0,
    meta JSONB NOT NULL DEFAULT '{}'::jsonb,
    rows_data JSONB NOT NULL DEFAULT '[]'::jsonb,
    published_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    is_active BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE INDEX IF NOT EXISTS idx_team_datasets_type_active
    ON public.team_datasets (dataset_type, is_active, published_at DESC);

ALTER TABLE public.team_datasets ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS team_datasets_select ON public.team_datasets;
CREATE POLICY team_datasets_select ON public.team_datasets
    FOR SELECT TO authenticated
    USING (true);

DROP POLICY IF EXISTS team_datasets_admin_write ON public.team_datasets;
CREATE POLICY team_datasets_admin_write ON public.team_datasets
    FOR ALL TO authenticated
    USING (public.is_admin())
    WITH CHECK (public.is_admin());

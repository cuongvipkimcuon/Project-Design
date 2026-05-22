-- Chia sẻ bảng kê: upload file Excel gzip (nhỏ hơn hàng trăm nghìn dòng JSON)

ALTER TABLE public.team_datasets
    ADD COLUMN IF NOT EXISTS file_gzip BYTEA;

ALTER TABLE public.team_datasets
    DROP CONSTRAINT IF EXISTS team_datasets_storage_format_check;

ALTER TABLE public.team_datasets
    ADD CONSTRAINT team_datasets_storage_format_check
    CHECK (storage_format IN ('inline', 'chunked', 'excel_gzip'));

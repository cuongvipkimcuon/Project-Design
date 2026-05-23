-- EMG scanner JSON + quy tắc Detail phiếu Supplier (team datasets)

ALTER TABLE public.team_datasets
    DROP CONSTRAINT IF EXISTS team_datasets_dataset_type_check;

ALTER TABLE public.team_datasets
    ADD CONSTRAINT team_datasets_dataset_type_check
    CHECK (dataset_type IN (
        'ol', 'bom_ke', 'supplier_template', 'emg_scanner', 'supplier_detail_rules'
    ));

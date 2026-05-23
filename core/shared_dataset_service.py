"""Admin publish OL / bảng kê lên Supabase — user khác pull về SQLite local."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from core.bom_ke_reader import BomKeLoadResult, BomKeReaderService
from core.team_pull_meta import mark_team_bom_pulled, mark_team_ol_pulled
from core.database import HubDatabase
from core.emg_scanner_reader import clear_emg_cache
from core.ol_reader import OL_COLUMNS, OlLoadResult, OlReaderService
from core.user_cloud import UserCloud
from core.utils import compute_file_md5, normalize_text


@dataclass
class TeamPullResult:
    messages: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    ol_result: OlLoadResult | None = None
    bom_result: BomKeLoadResult | None = None
    ops_pulled: bool = False
    ops_pushed: bool = False
    ops_version: int = 0


@dataclass
class TeamDatasetInfo:
    dataset_type: str
    file_name: str
    row_count: int
    publisher_name: str
    published_at: str
    content_hash: str
    meta: dict[str, Any]


def _json_default(value: object) -> object:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, (pd.Timestamp, datetime)):
        if pd.isna(value):
            return None
        if isinstance(value, pd.Timestamp):
            return value.to_pydatetime().isoformat()
        return value.isoformat()
    if isinstance(value, date) and not isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, float) and pd.isna(value):
        return None
    return value


def dataframe_to_records(df: pd.DataFrame) -> list[dict[str, Any]]:
    if df is None or df.empty:
        return []
    records: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        rec = {str(k): _json_default(row[k]) for k in df.columns}
        records.append(rec)
    return records


def records_to_dataframe(records: list[dict], *, dataset_type: str) -> pd.DataFrame:
    if not records:
        if dataset_type == "ol":
            return pd.DataFrame(columns=OL_COLUMNS)
        return pd.DataFrame()
    df = pd.DataFrame(records)
    date_cols_ol = (
        "order_date",
        "cutting",
        "stock",
        "estimate_delivery",
    )
    if dataset_type == "ol":
        for col in date_cols_ol:
            if col in df.columns:
                df[col] = pd.to_datetime(df[col], errors="coerce")
        if "excel_row" in df.columns:
            df["excel_row"] = pd.to_numeric(df["excel_row"], errors="coerce").fillna(0).astype(int)
        if "qty" in df.columns:
            df["qty"] = pd.to_numeric(df["qty"], errors="coerce")
    elif dataset_type == "bom_ke":
        if "order_date" in df.columns:
            df["order_date"] = pd.to_datetime(df["order_date"], errors="coerce")
        for col in ("row_index", "order_qty", "npl_qty_per_unit", "npl_qty_order"):
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


class SharedDatasetService:
    def __init__(self, db: HubDatabase) -> None:
        self.db = db
        self.cloud: UserCloud | None = db.cloud

    @property
    def cloud_enabled(self) -> bool:
        return self.cloud is not None and self.cloud.enabled

    def get_team_info(self, dataset_type: str) -> TeamDatasetInfo | None:
        if not self.cloud_enabled:
            return None
        row = self.cloud.get_active_team_dataset_header(dataset_type)
        if not row:
            return None
        return TeamDatasetInfo(
            dataset_type=str(row.get("dataset_type", "")),
            file_name=str(row.get("file_name", "")),
            row_count=int(row.get("row_count", 0) or 0),
            publisher_name=str(row.get("publisher_name", "")),
            published_at=str(row.get("published_at", "")),
            content_hash=str(row.get("content_hash", "")),
            meta=dict(row.get("meta") or {}),
        )

    def publish_ol(self, *, publisher_name: str) -> str:
        df = self.db.load_active_ol_df()
        if df is None or df.empty:
            meta = self.db.get_active_ol_dataset_meta()
            if meta:
                df = self.db._load_ol_rows_df(int(meta["id"]))
        if df is None or df.empty:
            raise ValueError("Chưa có dữ liệu OL — admin cần bấm Đọc OL trước.")
        active = self.db.get_active_ol_dataset_meta() or {}
        snapshot_date = date.today().strftime("%Y-%m-%d")
        snap = self.db.get_snapshot_meta(snapshot_date)
        if snap:
            snapshot_date = str(snap[1])
        payload_meta = {
            "snapshot_date": snapshot_date,
            "active_dataset_id": active.get("id"),
        }
        if not self.cloud_enabled:
            raise RuntimeError("Cloud chưa bật — đăng nhập Supabase và cấu hình .env.")
        self.cloud.publish_team_dataset(
            dataset_type="ol",
            publisher_name=publisher_name,
            file_name=str(active.get("file_name", "")),
            file_path=str(active.get("file_path", self.db.get_setup("ol_file_path", ""))),
            file_hash=str(active.get("file_hash", "")),
            content_hash=str(active.get("file_hash", "")),
            row_count=len(df),
            meta=payload_meta,
            rows_data=dataframe_to_records(df),
        )
        return f"Đã chia sẻ OL ({len(df)} dòng) lên cloud."

    def publish_bom_ke(self, *, publisher_name: str) -> str:
        a6_hash = self.db.get_setup("bom_ke_a6_hash", "")
        if not a6_hash:
            raise ValueError("Chưa có bảng kê — admin cần bấm Đọc bảng kê trước.")
        meta = self.db.get_bom_ke_dataset(a6_hash) or {}
        row_count = int(meta.get("row_count", 0) or 0)
        file_path = normalize_text(meta.get("file_path")) or self.db.get_setup(
            "bom_ke_file_path", ""
        )
        file_name = normalize_text(meta.get("file_name")) or Path(file_path).name
        if not file_path or not Path(file_path).is_file():
            raise ValueError("Không tìm thấy file bảng kê gốc — đọc lại từ Setup.")
        payload_meta = {
            "a6_text": self.db.get_setup("bom_ke_a6_text", ""),
            "a6_hash": a6_hash,
        }
        if not self.cloud_enabled:
            raise RuntimeError("Cloud chưa bật — đăng nhập Supabase và cấu hình .env.")
        self.cloud.publish_team_excel_file(
            dataset_type="bom_ke",
            publisher_name=publisher_name,
            file_name=file_name,
            file_path=file_path,
            file_hash=str(meta.get("file_hash", "")),
            content_hash=a6_hash,
            row_count=row_count,
            meta=payload_meta,
            excel_path=file_path,
        )
        raw_mb = Path(file_path).stat().st_size / (1024 * 1024)
        return (
            f"Đã chia sẻ file bảng kê ({file_name}, ~{raw_mb:.1f} MB, "
            f"{row_count:,} dòng sau khi đọc) — user tải file và parse local."
        )

    def pull_ol(self) -> OlLoadResult:
        if not self.cloud_enabled:
            raise RuntimeError("Cloud chưa bật.")
        row = self.cloud.get_active_team_dataset("ol")
        if not row:
            raise ValueError("Admin chưa chia sẻ OL — liên hệ admin bấm Đọc OL (hoặc Chia sẻ).")
        meta = dict(row.get("meta") or {})
        records = row.get("rows_data") or []
        if isinstance(records, str):
            records = json.loads(records)
        df = records_to_dataframe(list(records), dataset_type="ol")
        file_path = normalize_text(row.get("file_path")) or "[team-shared]"
        file_hash = normalize_text(row.get("file_hash")) or "team"
        file_name = normalize_text(row.get("file_name")) or "team_ol.xlsx"
        snapshot_date = normalize_text(meta.get("snapshot_date")) or date.today().strftime("%Y-%m-%d")

        self.db.save_snapshot(snapshot_date, file_path, file_hash, df)
        self.db.set_setup("ol_file_path", file_path)
        self.db.set_setup("ol_file_name", file_name)
        self.db.set_file_hash(file_path, file_hash)

        dataset_meta = self.db.get_ol_dataset(file_name, file_hash)
        dataset_id = int(dataset_meta["id"]) if dataset_meta else None
        if dataset_id:
            self.db.set_active_ol_dataset(dataset_id)

        pub = normalize_text(row.get("publisher_name")) or "admin"
        when = normalize_text(row.get("published_at"))[:16]
        content_hash = normalize_text(row.get("content_hash")) or file_hash
        mark_team_ol_pulled(self.db, content_hash=content_hash)
        return OlLoadResult(
            source="team_cloud",
            snapshot_date=snapshot_date,
            file_path=file_path,
            file_hash=file_hash,
            row_count=len(df),
            message=f"Đã tải OL dùng chung ({len(df)} dòng) — {pub}, {when}.",
            df=df,
            dataset_id=dataset_id,
        )

    def _team_bom_cache_path(self, file_name: str, content_hash: str) -> Path:
        cache = Path(self.db.db_file).resolve().parent / "team_cache"
        cache.mkdir(parents=True, exist_ok=True)
        safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in file_name)[:80]
        return cache / f"bom_ke_{content_hash[:12]}_{safe}"

    def pull_bom_ke(self) -> BomKeLoadResult:
        if not self.cloud_enabled:
            raise RuntimeError("Cloud chưa bật.")
        header = self.cloud.get_active_team_dataset_header("bom_ke")
        if not header:
            raise ValueError("Admin chưa chia sẻ bảng kê — liên hệ admin.")
        storage = str(header.get("storage_format") or "")
        file_name = normalize_text(header.get("file_name")) or "team_bom_ke.xlsx"
        content_hash = normalize_text(header.get("content_hash")) or ""
        pub = normalize_text(header.get("publisher_name")) or "admin"
        when = normalize_text(header.get("published_at"))[:16]

        if storage == "excel_gzip":
            header, xlsx_bytes = self.cloud.fetch_team_excel_bytes("bom_ke")
            if not xlsx_bytes:
                raise ValueError("Không tải được file bảng kê từ cloud.")
            local_path = self._team_bom_cache_path(file_name, content_hash)
            local_path.write_bytes(xlsx_bytes)
            self.db.set_setup("bom_link", str(local_path))
            self.db.set_setup("bom_ke_file_path", str(local_path))
            result = BomKeReaderService(self.db).load(str(local_path), force=False)
            result.message = (
                f"Đã tải file bảng kê ({result.row_count:,} dòng, parse local) — {pub}, {when}."
            )
            result.source = "team_cloud_file"
            mark_team_bom_pulled(self.db, content_hash=content_hash)
            return result

        row = self.cloud.get_active_team_dataset("bom_ke")
        if not row:
            raise ValueError("Admin chưa chia sẻ bảng kê — liên hệ admin.")
        meta = dict(row.get("meta") or {})
        records = row.get("rows_data") or []
        if isinstance(records, str):
            records = json.loads(records)
        df = records_to_dataframe(list(records), dataset_type="bom_ke")
        file_path = normalize_text(row.get("file_path")) or "[team-shared]"
        file_hash = normalize_text(row.get("file_hash")) or "team"
        a6_text = normalize_text(meta.get("a6_text"))
        a6_hash = normalize_text(meta.get("a6_hash")) or normalize_text(row.get("content_hash"))

        self.db.save_bom_ke_dataset(file_path, file_hash, a6_text, a6_hash, df)
        BomKeReaderService(self.db)._persist_bom_ke_pointers(
            file_path, file_name, file_hash, a6_text, a6_hash, len(df)
        )
        self.db.set_setup("bom_link", file_path)
        mark_team_bom_pulled(self.db, content_hash=a6_hash)

        return BomKeLoadResult(
            source="team_cloud",
            file_path=file_path,
            file_name=file_name,
            file_hash=file_hash,
            a6_text=a6_text,
            a6_hash=a6_hash,
            row_count=len(df),
            message=f"Đã tải bảng kê dùng chung ({len(df):,} dòng JSON) — {pub}, {when}.",
            df=df,
        )

    def _team_template_cache_path(self, file_name: str, content_hash: str) -> Path:
        cache = Path(self.db.db_file).resolve().parent / "team_cache"
        cache.mkdir(parents=True, exist_ok=True)
        safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in file_name)[:80]
        return cache / f"supplier_tpl_{content_hash[:12]}_{safe}"

    def publish_supplier_template(self, *, publisher_name: str) -> str:
        from core.supplier_excel_export import (
            SETUP_KEY_TEMPLATE_CLOUD_HASH,
            SETUP_KEY_TEMPLATE_PATH,
            resolve_supplier_template_path,
        )

        tpl_path = resolve_supplier_template_path(self.db)
        path = Path(tpl_path)
        if not path.is_file():
            raise ValueError("Không tìm thấy file template — chọn file trong Setup trước.")
        file_name = path.name
        file_hash = compute_file_md5(str(path))
        if not self.cloud_enabled:
            raise RuntimeError("Cloud chưa bật — đăng nhập Supabase và cấu hình .env.")
        self.cloud.publish_team_excel_file(
            dataset_type="supplier_template",
            publisher_name=publisher_name,
            file_name=file_name,
            file_path=str(path),
            file_hash=file_hash,
            content_hash=file_hash,
            row_count=0,
            meta={"kind": "supplier_slip_template"},
            excel_path=str(path),
        )
        self.db.set_setup(SETUP_KEY_TEMPLATE_PATH, str(path))
        self.db.set_setup("supplier_template_file_name", file_name)
        self.db.set_setup(SETUP_KEY_TEMPLATE_CLOUD_HASH, file_hash)
        kb = path.stat().st_size // 1024
        return f"Đã chia sẻ template phiếu ({file_name}, {kb} KB) lên cloud."

    def pull_supplier_template(self) -> str:
        import hashlib

        from core.supplier_excel_export import SETUP_KEY_TEMPLATE_CLOUD_HASH, SETUP_KEY_TEMPLATE_PATH

        if not self.cloud_enabled:
            raise RuntimeError("Cloud chưa bật.")
        header = self.cloud.get_active_team_dataset_header("supplier_template")
        if not header:
            raise ValueError("Admin chưa chia sẻ template phiếu — liên hệ admin.")
        if str(header.get("storage_format") or "") != "excel_gzip":
            raise ValueError("Template trên cloud không đúng định dạng — admin chia sẻ lại.")
        _, xlsx_bytes = self.cloud.fetch_team_excel_bytes("supplier_template")
        if not xlsx_bytes:
            raise ValueError("Không tải được template từ cloud.")
        file_name = normalize_text(header.get("file_name")) or "supplier_template.xlsx"
        content_hash = normalize_text(header.get("content_hash")) or hashlib.md5(xlsx_bytes).hexdigest()
        local_path = self._team_template_cache_path(file_name, content_hash)
        local_path.write_bytes(xlsx_bytes)
        self.db.set_setup(SETUP_KEY_TEMPLATE_PATH, str(local_path))
        self.db.set_setup("supplier_template_file_name", file_name)
        self.db.set_setup(SETUP_KEY_TEMPLATE_CLOUD_HASH, content_hash)
        pub = normalize_text(header.get("publisher_name")) or "admin"
        when = normalize_text(header.get("published_at"))[:16]
        kb = len(xlsx_bytes) // 1024
        return f"Đã tải template dùng chung ({file_name}, {kb} KB) — {pub}, {when}."

    def sync_supplier_template_if_needed(self) -> str | None:
        """Tự tải template mới từ cloud nếu admin đã cập nhật."""
        from core.supplier_excel_export import SETUP_KEY_TEMPLATE_CLOUD_HASH, SETUP_KEY_TEMPLATE_PATH

        if not self.cloud_enabled:
            return None
        header = self.cloud.get_active_team_dataset_header("supplier_template")
        if not header:
            return None
        content_hash = normalize_text(header.get("content_hash"))
        if not content_hash:
            return None
        local_hash = normalize_text(self.db.get_setup(SETUP_KEY_TEMPLATE_CLOUD_HASH, ""))
        local_path = normalize_text(self.db.get_setup(SETUP_KEY_TEMPLATE_PATH, ""))
        if content_hash == local_hash and local_path and Path(local_path).is_file():
            return None
        try:
            return self.pull_supplier_template()
        except Exception as exc:
            print(f"[SharedDataset] sync supplier template: {exc}")
            return None

    def _team_file_cache_path(self, prefix: str, file_name: str, content_hash: str) -> Path:
        cache = Path(self.db.db_file).resolve().parent / "team_cache"
        cache.mkdir(parents=True, exist_ok=True)
        safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in file_name)[:80]
        return cache / f"{prefix}_{content_hash[:12]}_{safe}"

    def publish_detail_rules(self, *, publisher_name: str) -> str:
        from core.supplier_detail_rules import (
            SETUP_KEY_TEAM,
            SETUP_KEY_TEAM_HASH,
            load_team_detail_rules,
        )

        rules = load_team_detail_rules(self.db)
        raw = json.dumps(rules, ensure_ascii=False).encode("utf-8")
        content_hash = hashlib.md5(raw).hexdigest()
        if not self.cloud_enabled:
            raise RuntimeError("Cloud chưa bật — đăng nhập Supabase và cấu hình .env.")
        self.cloud.publish_team_dataset(
            dataset_type="supplier_detail_rules",
            publisher_name=publisher_name,
            file_name="supplier_detail_rules.json",
            file_path=SETUP_KEY_TEAM,
            file_hash=content_hash,
            content_hash=content_hash,
            row_count=len(rules),
            meta={"kind": "supplier_detail_rules"},
            rows_data=rules,
        )
        self.db.set_setup(SETUP_KEY_TEAM_HASH, content_hash, sync_cloud=False)
        return f"Đã chia sẻ quy tắc Detail ({len(rules)} quy tắc team) lên cloud."

    def pull_detail_rules(self) -> str:
        from core.supplier_detail_rules import (
            SETUP_KEY_TEAM,
            SETUP_KEY_TEAM_HASH,
            save_team_detail_rules,
        )

        if not self.cloud_enabled:
            raise RuntimeError("Cloud chưa bật.")
        row = self.cloud.get_active_team_dataset("supplier_detail_rules")
        if not row:
            raise ValueError("Admin chưa chia sẻ quy tắc Detail.")
        records = row.get("rows_data") or []
        if isinstance(records, str):
            records = json.loads(records)
        if not isinstance(records, list):
            records = []
        content_hash = normalize_text(row.get("content_hash")) or ""
        save_team_detail_rules(self.db, list(records))
        self.db.set_setup(SETUP_KEY_TEAM_HASH, content_hash, sync_cloud=False)
        pub = normalize_text(row.get("publisher_name")) or "admin"
        when = normalize_text(row.get("published_at"))[:16]
        return f"Đã tải quy tắc Detail team ({len(records)} quy tắc) — {pub}, {when}."

    def publish_emg_scanner(self, *, publisher_name: str) -> str:
        from core.emg_scanner_reader import resolve_emg_scanner_path

        path = resolve_emg_scanner_path(self.db)
        if not path or not path.is_file():
            raise ValueError("Không tìm thấy file EMG scanner — chọn file trong Setup trước.")
        file_name = path.name
        file_hash = compute_file_md5(str(path))
        if not self.cloud_enabled:
            raise RuntimeError("Cloud chưa bật.")
        self.cloud.publish_team_excel_file(
            dataset_type="emg_scanner",
            publisher_name=publisher_name,
            file_name=file_name,
            file_path=str(path),
            file_hash=file_hash,
            content_hash=file_hash,
            row_count=0,
            meta={"kind": "emg_scanner_json"},
            excel_path=str(path),
        )
        self.db.set_setup("emg_scanner_cloud_hash", file_hash, sync_cloud=False)
        mb = path.stat().st_size / (1024 * 1024)
        return f"Đã chia sẻ EMG scanner ({file_name}, ~{mb:.1f} MB) lên cloud."

    def pull_emg_scanner(self) -> str:
        if not self.cloud_enabled:
            raise RuntimeError("Cloud chưa bật.")
        header = self.cloud.get_active_team_dataset_header("emg_scanner")
        if not header:
            raise ValueError("Admin chưa chia sẻ EMG scanner.")
        if str(header.get("storage_format") or "") != "excel_gzip":
            raise ValueError("EMG trên cloud không đúng định dạng.")
        _, blob = self.cloud.fetch_team_excel_bytes("emg_scanner")
        if not blob:
            raise ValueError("Không tải được EMG scanner từ cloud.")
        file_name = normalize_text(header.get("file_name")) or "emg_scanner_export.json"
        content_hash = normalize_text(header.get("content_hash")) or hashlib.md5(blob).hexdigest()
        local_path = self._team_file_cache_path("emg_scanner", file_name, content_hash)
        local_path.write_bytes(blob)
        clear_emg_cache()
        self.db.set_setup("emg_scanner_json_path", str(local_path), sync_cloud=False)
        self.db.set_setup("emg_scanner_cloud_hash", content_hash, sync_cloud=False)
        pub = normalize_text(header.get("publisher_name")) or "admin"
        when = normalize_text(header.get("published_at"))[:16]
        mb = len(blob) / (1024 * 1024)
        return f"Đã tải EMG scanner ({file_name}, ~{mb:.1f} MB) — {pub}, {when}."

    def publish_all_team_data(self, *, publisher_name: str) -> list[str]:
        msgs: list[str] = []
        for label, fn in [
            ("OL", lambda: self.publish_ol(publisher_name=publisher_name)),
            ("Bảng kê", lambda: self.publish_bom_ke(publisher_name=publisher_name)),
            ("Template phiếu", lambda: self.publish_supplier_template(publisher_name=publisher_name)),
            ("Quy tắc Detail", lambda: self.publish_detail_rules(publisher_name=publisher_name)),
            ("EMG scanner", lambda: self.publish_emg_scanner(publisher_name=publisher_name)),
        ]:
            try:
                msgs.append(fn())
            except Exception as exc:
                msgs.append(f"{label}: {exc}")
        return msgs

    def pull_all_team_data(self, *, skip_missing: bool = True) -> TeamPullResult:
        result = TeamPullResult()

        def _pull(label: str, fn) -> None:
            try:
                out = fn()
                if isinstance(out, OlLoadResult):
                    result.ol_result = out
                    result.messages.append(out.message)
                elif isinstance(out, BomKeLoadResult):
                    result.bom_result = out
                    result.messages.append(out.message)
                else:
                    result.messages.append(str(out))
            except Exception as exc:
                text = f"{label}: {exc}"
                if skip_missing:
                    result.errors.append(text)
                else:
                    raise RuntimeError(text) from exc

        if not self.cloud_enabled:
            raise RuntimeError("Cloud chưa bật.")
        _pull("OL", self.pull_ol)
        _pull("Bảng kê", self.pull_bom_ke)
        _pull("Template phiếu", self.pull_supplier_template)
        _pull("Quy tắc Detail", self.pull_detail_rules)
        _pull("EMG scanner", self.pull_emg_scanner)
        try:
            from core.team_ops_sync import TeamOpsSyncService

            ops = TeamOpsSyncService(self.db).sync_bidirectional(
                actor_name=normalize_text(getattr(self.cloud, "owner_id", "")),
            )
            result.ops_pulled = ops.pulled
            result.ops_pushed = ops.pushed
            result.ops_version = ops.version
            if ops.message:
                result.messages.append(ops.message)
            if ops.errors:
                result.errors.extend(ops.errors)
        except Exception as exc:
            result.errors.append(f"Plan/phiếu/tồn: {exc}")
        return result

    def sync_all_team_data_if_needed(self) -> TeamPullResult | None:
        """Login: tải các bản cloud mới (bỏ qua mục chưa có / lỗi)."""
        if not self.cloud_enabled:
            return None
        try:
            return self.pull_all_team_data(skip_missing=True)
        except Exception as exc:
            print(f"[SharedDataset] sync all: {exc}")
            return None

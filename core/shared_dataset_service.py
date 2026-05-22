"""Admin publish OL / bảng kê lên Supabase — user khác pull về SQLite local."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from core.bom_ke_reader import BomKeLoadResult, BomKeReaderService
from core.database import HubDatabase
from core.ol_reader import OL_COLUMNS, OlLoadResult, OlReaderService
from core.user_cloud import UserCloud
from core.utils import normalize_text


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

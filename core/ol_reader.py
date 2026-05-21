"""Order List (OL) Excel reader with daily snapshot cache."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from core.database import HubDatabase
from core.utils import (
    compute_file_signature,
    extract_customer_code_from_product_code,
    extract_item_code_from_product_code,
    format_date_dd_mm_yyyy,
    looks_like_dg_case,
    normalize_dg_case,
    normalize_text,
    parse_date_dd_mm_yyyy,
)

# Column indices (0-based), sheet 1 row 1 = header
COL_ORDER_DATE = 0   # A
COL_ORDER_NO = 1     # B
COL_DG_CASE = 2      # C
COL_CUSTOMER = 5     # F
COL_QTY = 6          # G
COL_PROD_NO = 7      # H
COL_PROD_NAME = 8    # I
COL_LOGO = 9         # J
COL_COLOR = 10       # K
COL_SUPPLIER = 11    # L
COL_SHIPDATE = 12    # M
COL_MATERIAL = 14    # O
COL_CUTTING = 16     # Q
COL_STOCK = 31       # AF
COL_EST_DELIVERY = 35  # AJ
MIN_COLUMNS = COL_EST_DELIVERY + 1

OL_COLUMNS = [
    "order_date",
    "order_no",
    "dg_case",
    "customer",
    "qty",
    "production_no",
    "production_name",
    "logo",
    "color",
    "supplier",
    "shipdate",
    "material",
    "cutting",
    "stock",
    "estimate_delivery",
    "customer_code",
    "item_code",
    "excel_row",
]


@dataclass
class OlLoadResult:
    source: str  # "cache_file" | "cache_snapshot" | "parsed" | "active_dataset"
    snapshot_date: str
    file_path: str
    file_hash: str
    row_count: int
    message: str
    df: pd.DataFrame
    dataset_id: int | None = None


class OlReaderService:
    def __init__(self, db: HubDatabase | None = None):
        self.db = db or HubDatabase()

    def _cell(self, row: pd.Series, col: int) -> object:
        if col < len(row):
            return row.iloc[col]
        return None

    def parse_ol_excel(self, file_path: str) -> pd.DataFrame:
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"Không tìm thấy file OL: {file_path}")

        df_raw = pd.read_excel(file_path, sheet_name=0, header=None)
        if df_raw.empty:
            raise ValueError("Sheet 1 của OL trống.")
        if df_raw.shape[1] < MIN_COLUMNS:
            raise ValueError(
                f"OL thiếu cột (cần tối thiểu đến AJ = {MIN_COLUMNS} cột, "
                f"file có {df_raw.shape[1]} cột)."
            )

        # Dòng đầu là header — bỏ qua
        data = df_raw.iloc[1:].copy()
        rows: list[dict] = []
        for idx, row in data.iterrows():
            dg = normalize_dg_case(self._cell(row, COL_DG_CASE))
            if not looks_like_dg_case(dg):
                continue

            order_dt = parse_date_dd_mm_yyyy(self._cell(row, COL_ORDER_DATE))
            cutting_dt = parse_date_dd_mm_yyyy(self._cell(row, COL_CUTTING))
            stock_dt = parse_date_dd_mm_yyyy(self._cell(row, COL_STOCK))
            est_dt = parse_date_dd_mm_yyyy(self._cell(row, COL_EST_DELIVERY))

            prod_no = normalize_text(self._cell(row, COL_PROD_NO))
            rows.append(
                {
                    "order_date": order_dt,
                    "order_date_str": format_date_dd_mm_yyyy(order_dt),
                    "order_no": normalize_text(self._cell(row, COL_ORDER_NO)),
                    "dg_case": dg,
                    "customer": normalize_text(self._cell(row, COL_CUSTOMER)),
                    "qty": self._cell(row, COL_QTY),
                    "production_no": prod_no,
                    "production_name": normalize_text(self._cell(row, COL_PROD_NAME)),
                    "logo": normalize_text(self._cell(row, COL_LOGO)),
                    "color": normalize_text(self._cell(row, COL_COLOR)),
                    "supplier": normalize_text(self._cell(row, COL_SUPPLIER)),
                    "shipdate": normalize_text(self._cell(row, COL_SHIPDATE)),
                    "material": normalize_text(self._cell(row, COL_MATERIAL)),
                    "cutting": cutting_dt,
                    "cutting_str": format_date_dd_mm_yyyy(cutting_dt),
                    "stock": stock_dt,
                    "stock_str": format_date_dd_mm_yyyy(stock_dt),
                    "estimate_delivery": est_dt,
                    "estimate_delivery_str": format_date_dd_mm_yyyy(est_dt),
                    "customer_code": extract_customer_code_from_product_code(prod_no),
                    "item_code": extract_item_code_from_product_code(prod_no),
                    "excel_row": int(idx) + 1,
                }
            )

        if not rows:
            return pd.DataFrame(columns=OL_COLUMNS)
        return pd.DataFrame(rows)

    def load_for_today(
        self,
        file_path: str,
        *,
        force: bool = False,
        snapshot_date: str | None = None,
    ) -> OlLoadResult:
        """Đọc OL cho ngày snapshot (mặc định hôm nay). Cache theo tên file + hash."""
        path = str(Path(file_path).resolve())
        file_name = Path(path).name
        snap = snapshot_date or date.today().strftime("%Y-%m-%d")
        file_hash = compute_file_signature(path)

        if not force:
            cached = self.db.get_ol_dataset(file_name, file_hash)
            if cached:
                df = self.db.load_ol_dataset_df(file_name, file_hash)
                if df is not None:
                    self.db.save_snapshot(snap, path, file_hash, df)
                    return self._finish_ol_load(
                        source="cache_file",
                        snapshot_date=snap,
                        file_path=path,
                        file_hash=file_hash,
                        df=df,
                        file_name=file_name,
                        cache_note=f"Dùng cache OL theo file '{file_name}'",
                    )

            meta = self.db.get_snapshot_meta(snap)
            if meta and meta[2] == path and meta[3] == file_hash:
                df = self.db.load_snapshot_df(snap)
                if df is not None:
                    return self._finish_ol_load(
                        source="cache_snapshot",
                        snapshot_date=snap,
                        file_path=path,
                        file_hash=file_hash,
                        df=df,
                        file_name=file_name,
                        cache_note=f"Dùng snapshot ngày {snap} (file không đổi)",
                    )

        df = self.parse_ol_excel(path)
        self.db.save_snapshot(snap, path, file_hash, df)
        self.db.set_file_hash(path, file_hash)
        self.db.set_setup("ol_file_path", path)
        self.db.set_setup("ol_file_name", file_name)

        return self._finish_ol_load(
            source="parsed",
            snapshot_date=snap,
            file_path=path,
            file_hash=file_hash,
            df=df,
            file_name=file_name,
            cache_note=f"Đã đọc {len(df)} dòng OL từ '{file_name}' — lưu snapshot {snap}",
        )

    def _finish_ol_load(
        self,
        *,
        source: str,
        snapshot_date: str,
        file_path: str,
        file_hash: str,
        df: pd.DataFrame,
        file_name: str,
        cache_note: str,
    ) -> OlLoadResult:
        meta = self.db.get_ol_dataset(file_name, file_hash)
        dataset_id = int(meta["id"]) if meta else None
        if dataset_id:
            self.db.set_active_ol_dataset(dataset_id)
        return OlLoadResult(
            source=source,
            snapshot_date=snapshot_date,
            file_path=file_path,
            file_hash=file_hash,
            row_count=len(df),
            message=f"{cache_note} ({len(df)} dòng).",
            df=df,
            dataset_id=dataset_id,
        )

    def load_active_dataset(self) -> OlLoadResult | None:
        """OL dataset vừa đọc gần nhất — dùng cho Planning / autofill."""
        meta = self.db.get_active_ol_dataset_meta()
        if not meta:
            return None
        df = self.db.load_active_ol_df()
        if df is None:
            return None
        read_at = self.db.get_setup("ol_active_read_at", "")
        file_name = normalize_text(meta.get("file_name"))
        when = f", đọc lúc {read_at}" if read_at else ""
        return OlLoadResult(
            source="active_dataset",
            snapshot_date=date.today().strftime("%Y-%m-%d"),
            file_path=str(meta.get("file_path", "")),
            file_hash=str(meta.get("file_hash", "")),
            row_count=len(df),
            message=f"OL đang dùng: '{file_name}' ({len(df)} dòng{when}).",
            df=df,
            dataset_id=int(meta["id"]),
        )

    def load_snapshot(self, snapshot_date: str) -> OlLoadResult | None:
        meta = self.db.get_snapshot_meta(snapshot_date)
        if not meta:
            return None
        df = self.db.load_snapshot_df(snapshot_date)
        if df is None:
            return None
        return OlLoadResult(
            source="cache_snapshot",
            snapshot_date=snapshot_date,
            file_path=str(meta[2]),
            file_hash=str(meta[3]),
            row_count=len(df),
            message=f"Đã tải snapshot ngày {snapshot_date} ({len(df)} dòng).",
            df=df,
        )

    def find_by_dg_case(self, df: pd.DataFrame, dg_case: str) -> pd.DataFrame:
        key = normalize_dg_case(dg_case)
        if not key or df.empty:
            return df.iloc[0:0].copy()
        mask = df["dg_case"].map(
            lambda x: key == normalize_dg_case(x) or key in normalize_dg_case(x)
        )
        return df[mask].copy()

    @staticmethod
    def _qty_total(values) -> tuple[float, bool]:
        total = 0.0
        has_qty = False
        for val in values:
            if val is None or (isinstance(val, float) and pd.isna(val)):
                continue
            has_qty = True
            try:
                total += float(val)
            except (TypeError, ValueError):
                pass
        return total, has_qty

    @staticmethod
    def _format_qty(total: float) -> str:
        if total == int(total):
            return str(int(total))
        text = f"{total:.4f}".rstrip("0").rstrip(".")
        return text or "0"

    def summarize_for_planning(self, df: pd.DataFrame, dg_case: str) -> dict[str, str]:
        """Lấy đúng cột đã lưu khi đọc OL: production_no, supplier, qty (cộng nếu tách dòng)."""
        matches = self.find_by_dg_case(df, dg_case)
        empty = {"production_no": "", "supplier": "", "quantity": ""}
        if matches.empty:
            return empty

        supplier = ""
        if "supplier" in matches.columns:
            for val in matches["supplier"]:
                text = normalize_text(val)
                if text:
                    supplier = text
                    break

        production_no = ""
        if "production_no" in matches.columns:
            codes = [normalize_text(v) for v in matches["production_no"] if normalize_text(v)]
            if codes:
                production_no = list(dict.fromkeys(codes))[0]

        total_qty, has_qty = self._qty_total(matches["qty"]) if "qty" in matches.columns else (0.0, False)

        return {
            "production_no": production_no,
            "supplier": supplier,
            "quantity": self._format_qty(total_qty) if has_qty else "",
        }

    def filter_by_order_date(self, df: pd.DataFrame, order_date: str) -> pd.DataFrame:
        if df.empty:
            return df
        target = parse_date_dd_mm_yyyy(order_date)
        if target is None:
            sub = df[df["order_date_str"] == order_date]
            return sub.copy()
        return df[
            df["order_date"].map(
                lambda d: isinstance(d, datetime)
                and d.date() == target.date()
                if d is not None
                else False
            )
        ].copy()

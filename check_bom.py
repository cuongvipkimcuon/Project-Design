import hashlib
import logging
import math
import os
import pickle
import sqlite3
import threading
import tkinter as tk
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, simpledialog, ttk

import pandas as pd


DB_FILE = "check_bom.db"
LOG_FILE = "check_bom.log"


logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)


def normalize_text(value: object) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if text.lower() == "nan":
        return ""
    return text


def normalize_key(value: object) -> str:
    return normalize_text(value).lower()


def normalize_npl_code(value: object) -> str:
    # Dong bo ma NPL: thay khoang trang bang dau cham de khop bang ke.
    return normalize_text(value).replace(" ", ".")


def normalize_dg_case(value: object) -> str:
    text = normalize_text(value).upper().replace(" ", "")
    if not text:
        return ""
    if text.startswith("0-"):
        text = "O-" + text[2:]
    return text


def safe_float(value: object) -> float | None:
    if value is None:
        return None
    text = normalize_text(value).replace(",", ".")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def ellipsis_text(s: object, max_len: int) -> str:
    t = normalize_text(s)
    if max_len <= 3:
        return t[:max_len] if t else ""
    if len(t) <= max_len:
        return t
    return t[: max_len - 3] + "..."


def format_scalar_for_cell(value: object, *, compact: bool) -> str:
    """Hien thi gia tri trong o bang: compact = rut gon so; detail = day du hon."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value)
    try:
        f = float(value)
    except (TypeError, ValueError, OverflowError):
        return normalize_text(value)
    if f != f:
        return ""
    if compact:
        return f"{f:.6g}"
    s = f"{f:.15f}".rstrip("0").rstrip(".")
    return s if s else str(f)


def format_pair_cell(
    label_a: str, val_a: object, label_b: str, val_b: object, *, compact: bool
) -> str:
    sa = format_scalar_for_cell(val_a, compact=compact)
    sb = format_scalar_for_cell(val_b, compact=compact)
    return f"{label_a}:{sa} | {label_b}:{sb}"


def format_full_row_log(row: object, la: str, lb: str, qa: str, qb: str) -> str:
    """Log day du mot dong ket qua (khong rut gon)."""
    r = row if isinstance(row, pd.Series) else pd.Series(row)
    sldm = format_pair_cell(la, r.get("sldm1_ke"), lb, r.get("sldm1_bom"), compact=False)
    qty = format_pair_cell(qa, r.get("so_luong_ke"), qb, r.get("so_luong_bom"), compact=False)
    lines = [
        f"dg_case: {normalize_text(r.get('dg_case', ''))}",
        f"ma_npl: {normalize_text(r.get('ma_npl', ''))}",
        f"ten_npl: {normalize_text(r.get('ten_npl', ''))}",
        f"mo_ta: {normalize_text(r.get('mo_ta', ''))}",
        f"dvt: {normalize_text(r.get('dvt', ''))}",
        f"sldm1: {sldm}",
        f"so_luong: {qty}",
        f"khac: {normalize_text(r.get('khac', ''))}",
        f"chi_tiet: {normalize_text(r.get('chi_tiet', ''))}",
        f"trang_thai: {normalize_text(r.get('trang_thai', ''))}",
        f"row_kind: {normalize_text(r.get('row_kind', ''))}",
    ]
    return "\n".join(lines)


def format_measure_value(value: object, dvt: object, *, compact: bool) -> str:
    if value is None:
        return ""
    try:
        f = float(value)
    except (TypeError, ValueError, OverflowError):
        return normalize_text(value)
    if f != f:
        return ""
    if not compact:
        return format_scalar_for_cell(f, compact=False)
    unit = normalize_key(dvt)
    if unit == "m":
        return f"{f:.2f}"
    return str(int(math.ceil(f)))


def format_measure_pair_short(label_a: str, val_a: object, label_b: str, val_b: object, dvt: object) -> str:
    sa = format_measure_value(val_a, dvt, compact=True)
    sb = format_measure_value(val_b, dvt, compact=True)
    return f"{label_a}:{sa} | {label_b}:{sb}"


def infer_row_kind_from_row(row: object) -> str:
    """Khi DataFrame cu khong co cot row_kind."""
    r = row if isinstance(row, pd.Series) else pd.Series(row)
    if normalize_text(r.get("trang_thai")) == "✔️":
        return "ok"
    ct = normalize_text(r.get("chi_tiet", "")).lower()
    if "khong co" in ct and ("tieu diem" in ct or "doi chieu" in ct):
        return "presence"
    if "thieu dong" in ct or "thua dong" in ct:
        return "presence"
    return "qty"


def compute_file_md5(file_path: str) -> str:
    md5 = hashlib.md5()
    with open(file_path, "rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            md5.update(chunk)
    return md5.hexdigest()


def compute_file_signature(file_path: str) -> str:
    """Fast signature from file stat (size + mtime_ns), much faster than MD5."""
    st = Path(file_path).stat()
    return f"stat:{st.st_size}:{st.st_mtime_ns}"


def extract_customer_code_from_product_code(product_code: object) -> str:
    text = normalize_text(product_code)
    if not text:
        return ""
    parts = [p.strip() for p in text.split(".") if p.strip()]
    if len(parts) >= 2:
        return parts[1]
    return ""


def extract_item_code_from_product_code(product_code: object) -> str:
    """Ma hang (xxxx) trong ma SP dang *.*.xxxx.* — dung de tim file trong thu muc."""
    text = normalize_text(product_code)
    if not text:
        return ""
    parts = [p.strip() for p in text.split(".") if p.strip()]
    if len(parts) >= 3:
        return parts[2]
    return ""


def normalized_pm_quantity(row: pd.Series) -> float | None:
    """So luong cot P (so_luong) chia cho cot G bang ke truoc khi so sanh."""
    qty = safe_float(row.get("so_luong"))
    if qty is None:
        return None
    g = safe_float(row.get("qty_divisor"))
    if g is None or g == 0:
        return qty
    return qty / g


def round_measure_value(value: float | None, dvt: object) -> float | None:
    if value is None:
        return None
    unit = normalize_key(dvt)
    if unit == "m":
        return round(float(value), 2)
    return float(math.ceil(float(value)))


def looks_like_npl_code(value: object) -> bool:
    t = normalize_npl_code(value)
    if not t:
        return False
    low = t.lower()
    if low in {"m", "m2", "m3", "pcs", "pc", "pair", "set", "roll", "kg", "g", "ml", "l", "carton"}:
        return False
    return any(ch.isdigit() for ch in t)


@dataclass
class CompareResult:
    ma_npl: str
    ten_npl: str
    mo_ta: str
    dvt: str
    sldm1_ke: float | None
    so_luong_ke: float | None
    sldm1_bom: float | None
    so_luong_bom: float | None
    khac: str
    chi_tiet: str
    trang_thai: str
    dg_case: str = ""
    # ok = chuan; qty = lech SLDM1 / so luong; presence = thieu hoac thua loai NPL
    row_kind: str = "ok"


class DatabaseManager:
    def __init__(self, db_file: str = DB_FILE):
        self.db_file = db_file
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_file)
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _init_db(self) -> None:
        conn = self._connect()
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS setup (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key TEXT UNIQUE NOT NULL,
                value TEXT
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS customers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_name TEXT NOT NULL,
                code TEXT,
                folder_link TEXT NOT NULL
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS mapping (
                dg_case TEXT PRIMARY KEY,
                file_path TEXT NOT NULL,
                sheet_name TEXT NOT NULL,
                cell TEXT NOT NULL,
                file_hash TEXT NOT NULL
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS hash_cache (
                file_path TEXT NOT NULL,
                sheet_name TEXT NOT NULL,
                hash_value TEXT NOT NULL,
                data BLOB NOT NULL,
                last_used TEXT NOT NULL,
                PRIMARY KEY (file_path, sheet_name)
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS bom_ke (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                dg_case TEXT,
                row_index INTEGER,
                order_date TEXT,
                ma_npl TEXT,
                ten_npl TEXT,
                mo_ta TEXT,
                don_vi_tinh TEXT,
                so_luong_dm_1 REAL,
                so_luong REAL,
                hash_bom_line TEXT
            )
            """
        )
        conn.commit()
        conn.close()

    def get_setup_value(self, key: str) -> str:
        conn = self._connect()
        cur = conn.cursor()
        row = cur.execute("SELECT value FROM setup WHERE key = ?", (key,)).fetchone()
        conn.close()
        return str(row[0]) if row and row[0] is not None else ""

    def set_setup_value(self, key: str, value: str) -> None:
        conn = self._connect()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO setup(key, value)
            VALUES(?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, value),
        )
        conn.commit()
        conn.close()

    def get_customers(self) -> list[tuple]:
        conn = self._connect()
        cur = conn.cursor()
        rows = cur.execute(
            "SELECT id, customer_name, code, folder_link FROM customers ORDER BY id ASC"
        ).fetchall()
        conn.close()
        return rows

    def add_customer(self, customer_name: str, code: str, folder_link: str) -> None:
        conn = self._connect()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO customers(customer_name, code, folder_link) VALUES (?, ?, ?)",
            (customer_name, code, folder_link),
        )
        conn.commit()
        conn.close()

    def update_customer(self, row_id: int, customer_name: str, code: str, folder_link: str) -> None:
        conn = self._connect()
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE customers
            SET customer_name = ?, code = ?, folder_link = ?
            WHERE id = ?
            """,
            (customer_name, code, folder_link, row_id),
        )
        conn.commit()
        conn.close()

    def delete_customer(self, row_id: int) -> None:
        conn = self._connect()
        cur = conn.cursor()
        cur.execute("DELETE FROM customers WHERE id = ?", (row_id,))
        conn.commit()
        conn.close()

    def get_mappings(self) -> list[tuple]:
        conn = self._connect()
        cur = conn.cursor()
        rows = cur.execute(
            """
            SELECT dg_case, file_path, sheet_name, cell, file_hash
            FROM mapping
            ORDER BY dg_case
            """
        ).fetchall()
        conn.close()
        return rows

    def get_mapping(self, dg_case: str) -> tuple | None:
        conn = self._connect()
        cur = conn.cursor()
        row = cur.execute(
            """
            SELECT dg_case, file_path, sheet_name, cell, file_hash
            FROM mapping
            WHERE dg_case = ?
            """,
            (dg_case,),
        ).fetchone()
        conn.close()
        return row

    def upsert_mapping(self, dg_case: str, file_path: str, sheet_name: str, cell: str, file_hash: str) -> None:
        conn = self._connect()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO mapping(dg_case, file_path, sheet_name, cell, file_hash)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(dg_case) DO UPDATE SET
                file_path = excluded.file_path,
                sheet_name = excluded.sheet_name,
                cell = excluded.cell,
                file_hash = excluded.file_hash
            """,
            (dg_case, file_path, sheet_name, cell, file_hash),
        )
        conn.commit()
        conn.close()

    def delete_mapping(self, dg_case: str) -> None:
        conn = self._connect()
        cur = conn.cursor()
        cur.execute("DELETE FROM mapping WHERE dg_case = ?", (dg_case,))
        conn.commit()
        conn.close()

    def get_cache(self, file_path: str, sheet_name: str) -> tuple | None:
        conn = self._connect()
        cur = conn.cursor()
        row = cur.execute(
            """
            SELECT hash_value, data
            FROM hash_cache
            WHERE file_path = ? AND sheet_name = ?
            """,
            (file_path, sheet_name),
        ).fetchone()
        conn.close()
        return row

    def upsert_cache(self, file_path: str, sheet_name: str, hash_value: str, data_blob: bytes) -> None:
        now = datetime.now().isoformat(timespec="seconds")
        conn = self._connect()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO hash_cache(file_path, sheet_name, hash_value, data, last_used)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(file_path, sheet_name) DO UPDATE SET
                hash_value = excluded.hash_value,
                data = excluded.data,
                last_used = excluded.last_used
            """,
            (file_path, sheet_name, hash_value, data_blob, now),
        )
        conn.commit()
        conn.close()

    def touch_cache(self, file_path: str, sheet_name: str) -> None:
        now = datetime.now().isoformat(timespec="seconds")
        conn = self._connect()
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE hash_cache
            SET last_used = ?
            WHERE file_path = ? AND sheet_name = ?
            """,
            (now, file_path, sheet_name),
        )
        conn.commit()
        conn.close()

    def get_all_cache_rows(self) -> list[tuple]:
        conn = self._connect()
        cur = conn.cursor()
        rows = cur.execute(
            """
            SELECT file_path, sheet_name, hash_value, last_used
            FROM hash_cache
            ORDER BY last_used DESC
            """
        ).fetchall()
        conn.close()
        return rows

    def delete_cache_older_than(self, days: int) -> int:
        cutoff = (datetime.now() - timedelta(days=days)).isoformat(timespec="seconds")
        conn = self._connect()
        cur = conn.cursor()
        cur.execute("DELETE FROM hash_cache WHERE last_used < ?", (cutoff,))
        affected = cur.rowcount if cur.rowcount is not None else 0
        conn.commit()
        conn.close()
        return int(affected)

    def delete_cache_entry(self, file_path: str, sheet_name: str) -> None:
        conn = self._connect()
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM hash_cache WHERE file_path = ? AND sheet_name = ?",
            (file_path, sheet_name),
        )
        conn.commit()
        conn.close()

    def clear_cache(self) -> None:
        conn = self._connect()
        cur = conn.cursor()
        cur.execute("DELETE FROM hash_cache")
        conn.commit()
        conn.close()


class ExcelParser:
    def __init__(self, db: DatabaseManager):
        self.db = db

    def load_bom_ke(self, file_path: str) -> pd.DataFrame:
        try:
            from core.bom_ke_reader import BomKeReaderService
            from core.database import HubDatabase

            result = BomKeReaderService(HubDatabase()).load(file_path, force=False)
            return result.df
        except Exception:
            pass
        if not Path(file_path).exists():
            raise FileNotFoundError(f"Khong tim thay bang ke: {file_path}")
        file_hash = compute_file_signature(file_path)
        cache_key = "BOM_KE_V3"
        cached = self.db.get_cache(file_path, cache_key)
        if cached and cached[0] == file_hash:
            self.db.touch_cache(file_path, cache_key)
            logging.info("Load bang ke tu cache: %s", file_path)
            return pickle.loads(cached[1])

        df_raw = pd.read_excel(file_path, sheet_name=0, header=None)
        if df_raw.empty:
            raise ValueError("Bang ke rong.")
        if df_raw.shape[1] < 16:
            raise ValueError("Bang ke khong du cot (can toi thieu cot P).")

        out = pd.DataFrame(
            {
                "row_index": df_raw.index + 1,
                "dg_case": df_raw.iloc[:, 0].map(normalize_text),
                "order_date": pd.to_datetime(df_raw.iloc[:, 1], errors="coerce"),
                "product_code": df_raw.iloc[:, 3].map(normalize_text),
                "qty_divisor": pd.to_numeric(df_raw.iloc[:, 6], errors="coerce"),
                "ma_npl": df_raw.iloc[:, 9].map(normalize_text),
                "ten_npl": df_raw.iloc[:, 10].map(normalize_text),
                "mo_ta": df_raw.iloc[:, 11].map(normalize_text),
                "don_vi_tinh": df_raw.iloc[:, 13].map(normalize_text),
                "so_luong_dm_1": pd.to_numeric(df_raw.iloc[:, 14], errors="coerce"),
                "so_luong": pd.to_numeric(df_raw.iloc[:, 15], errors="coerce"),
            }
        )
        out["customer_code"] = out["product_code"].map(extract_customer_code_from_product_code)
        out["item_code"] = out["product_code"].map(extract_item_code_from_product_code)
        out = out[(out["dg_case"] != "") & (out["product_code"] != "")].copy()
        blob = pickle.dumps(out)
        self.db.upsert_cache(file_path, cache_key, file_hash, blob)
        logging.info("Parse bang ke moi va luu cache: %s", file_path)
        return out

    def load_bom_sheet(self, file_path: str, sheet_name: str) -> pd.DataFrame:
        if not Path(file_path).exists():
            raise FileNotFoundError(f"Khong tim thay file BOM: {file_path}")
        file_hash = compute_file_signature(file_path)
        cache_key = f"{sheet_name}|BOM_EXCEL_V2"
        cached = self.db.get_cache(file_path, cache_key)
        if cached and cached[0] == file_hash:
            self.db.touch_cache(file_path, cache_key)
            logging.info("Load BOM sheet tu cache: %s | %s", file_path, sheet_name)
            return pickle.loads(cached[1])

        df_raw = pd.read_excel(file_path, sheet_name=sheet_name, header=None)
        if df_raw.empty:
            raise ValueError(f"Sheet {sheet_name} rong.")

        if df_raw.shape[1] < 12:
            raise ValueError(f"Sheet {sheet_name} khong du cot (can toi thieu cot L).")
        # Quy tac Check Excel:
        # - Lay dong co cot I co du lieu.
        # - ma_npl: COT A, chuan hoa "space -> '.'" de khop bang ke.
        # - sldm1: cot H
        # - so_luong: cot I, neu cot K co du lieu thi lay cot K
        # - dvt: neu lay I thi cot J, neu lay K thi cot L
        df = df_raw.copy()
        col_i_txt = df.iloc[:, 8].map(normalize_text) if df.shape[1] > 8 else pd.Series([""] * len(df), index=df.index)
        col_a_txt = df.iloc[:, 0].map(normalize_text) if df.shape[1] > 0 else pd.Series([""] * len(df), index=df.index)
        valid = (col_i_txt != "") & (col_a_txt != "")
        d = df[valid].copy()

        qty_i = pd.to_numeric(d.iloc[:, 8], errors="coerce")
        qty_k = pd.to_numeric(d.iloc[:, 10], errors="coerce") if d.shape[1] > 10 else pd.Series([None] * len(d), index=d.index)
        use_k = qty_k.notna()
        qty = qty_i.where(~use_k, qty_k)
        dvt_i = d.iloc[:, 9].map(normalize_text) if d.shape[1] > 9 else pd.Series([""] * len(d), index=d.index)
        dvt_k = d.iloc[:, 11].map(normalize_text) if d.shape[1] > 11 else pd.Series([""] * len(d), index=d.index)
        dvt = dvt_i.where(~use_k, dvt_k)

        out = pd.DataFrame(
            {
                "ma_npl": d.iloc[:, 0].map(normalize_npl_code),
                "ten_npl": pd.Series([""] * len(d), index=d.index),
                "mo_ta": pd.Series([""] * len(d), index=d.index),
                "sldm1_h": pd.to_numeric(d.iloc[:, 7], errors="coerce"),
                "so_luong_i": qty,
                "so_luong_k": qty_k,
                "dvt_excel": dvt.map(normalize_text),
            }
        )
        out = out[out["ma_npl"] != ""].copy()
        blob = pickle.dumps(out)
        self.db.upsert_cache(file_path, cache_key, file_hash, blob)
        logging.info("Parse BOM sheet moi va luu cache: %s | %s", file_path, sheet_name)
        return out


class BomSearcher:
    def __init__(self, db: DatabaseManager):
        self.db = db

    def search_in_file(self, file_path: str, dg_case: str) -> tuple[str, str] | None:
        xls = pd.ExcelFile(file_path)
        target = normalize_key(dg_case)
        # Thuong nguoi dung tao sheet moi o cuoi file => quet tu cuoi len de tim nhanh hon.
        for sheet in reversed(xls.sheet_names):
            # Chi quet vung nho A1:B9 de tim DG case, tranh doc full sheet gay cham.
            df = pd.read_excel(
                file_path,
                sheet_name=sheet,
                header=None,
                usecols="A:B",
                nrows=9,
            )
            max_row = min(9, len(df))
            max_col = min(2, df.shape[1])
            for r in range(max_row):
                for c in range(max_col):
                    val = normalize_key(df.iat[r, c])
                    if val == target:
                        cell = f"{chr(ord('A') + c)}{r + 1}"
                        return sheet, cell
        return None

    def resolve_mapping(
        self,
        dg_case: str,
        customer_folder: str,
        item_code: str = "",
        progress_cb: callable | None = None,
    ) -> tuple[str, str, str]:
        mapped = self.db.get_mapping(dg_case)
        if mapped:
            _, file_path, sheet_name, cell, file_hash = mapped
            if Path(file_path).exists():
                if str(file_hash).startswith("stat:"):
                    current_hash = compute_file_signature(file_path)
                    if current_hash == file_hash:
                        return file_path, sheet_name, cell
                # Mapping cu/doi hash: van uu tien mapping nay (se parse lai sheet va cap nhat hash)
                return file_path, sheet_name, cell

        folder = Path(customer_folder)
        if not folder.exists():
            raise FileNotFoundError(f"Khong ton tai thu muc khach hang: {customer_folder}")
        all_excel = [p for p in folder.glob("*") if p.suffix.lower() in [".xlsx", ".xls"]]
        ic = normalize_key(item_code)
        if ic:
            excel_files = [p for p in all_excel if ic in normalize_key(p.name)]
            if not excel_files:
                raise ValueError(
                    f"Khong co file nao trong thu muc co chua ma SP '{item_code}'."
                )
        else:
            excel_files = list(all_excel)
        excel_files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        for i, fp in enumerate(excel_files, start=1):
            try:
                if progress_cb is not None:
                    progress_cb(
                        f"Dang quet file {i}/{len(excel_files)}: {fp.name}"
                    )
                found = self.search_in_file(str(fp), dg_case)
                if found:
                    sheet, cell = found
                    f_hash = compute_file_signature(str(fp))
                    self.db.upsert_mapping(dg_case, str(fp), sheet, cell, f_hash)
                    return str(fp), sheet, cell
            except Exception as exc:
                logging.warning("Khong scan duoc file %s: %s", fp, exc)
                continue
        raise ValueError(f"Khong tim thay DG Case {dg_case} trong thu muc {customer_folder}")


class BomComparator:
    @staticmethod
    def is_quantity_match(dvt: str, value_ke: float | None, value_bom: float | None) -> bool:
        if value_ke is None or value_bom is None:
            return False
        unit = normalize_key(dvt)
        if unit == "m":
            return abs(value_ke - value_bom) <= 0.05 * abs(value_ke)
        return abs(value_ke - value_bom) <= 1

    @staticmethod
    def is_sldm1_match(value_ke: float | None, value_bom: float | None) -> bool:
        if value_ke is None or value_bom is None:
            return False
        return abs(value_ke - value_bom) <= 1

    @staticmethod
    def is_quantity_match_excel(dvt: str, value_ke: float | None, value_bom: float | None) -> bool:
        if value_ke is None or value_bom is None:
            return False
        unit = normalize_key(dvt)
        if unit == "m":
            return abs(value_ke - value_bom) <= 0.05 * abs(value_ke)
        return abs(math.ceil(value_ke) - math.ceil(value_bom)) <= 1

    def compare_pm_focus_vs_other(
        self,
        focus_df: pd.DataFrame,
        other_df: pd.DataFrame,
        focus_label: str,
        other_label: str,
    ) -> list[CompareResult]:
        """So tieu diem (focus) voi mot don khac; so luong so sanh sau khi chia cot G."""

        def to_map(df: pd.DataFrame) -> dict[str, pd.Series]:
            out: dict[str, pd.Series] = {}
            for _, row in df.iterrows():
                out[normalize_key(row["ma_npl"])] = row
            return out

        f_map = to_map(focus_df)
        o_map = to_map(other_df)
        union_keys = sorted({*f_map.keys(), *o_map.keys()})
        pair_txt = f"Tieu diem ({focus_label}) vs {other_label}"

        results: list[CompareResult] = []
        for key in union_keys:
            f_row = f_map.get(key)
            o_row = o_map.get(key)
            if f_row is None:
                results.append(
                    CompareResult(
                        ma_npl=normalize_text(o_row["ma_npl"]),
                        ten_npl=normalize_text(o_row["ten_npl"]),
                        mo_ta=normalize_text(o_row["mo_ta"]),
                        dvt=normalize_text(o_row["don_vi_tinh"]),
                        sldm1_ke=None,
                        so_luong_ke=None,
                        sldm1_bom=safe_float(o_row["so_luong_dm_1"]),
                        so_luong_bom=normalized_pm_quantity(o_row),
                        khac=pair_txt,
                        chi_tiet="Co trong don doi chieu, khong co o tieu diem",
                        trang_thai="❌",
                        dg_case=normalize_text(o_row.get("dg_case", "")),
                        row_kind="presence",
                    )
                )
                continue
            if o_row is None:
                results.append(
                    CompareResult(
                        ma_npl=normalize_text(f_row["ma_npl"]),
                        ten_npl=normalize_text(f_row["ten_npl"]),
                        mo_ta=normalize_text(f_row["mo_ta"]),
                        dvt=normalize_text(f_row["don_vi_tinh"]),
                        sldm1_ke=safe_float(f_row["so_luong_dm_1"]),
                        so_luong_ke=normalized_pm_quantity(f_row),
                        sldm1_bom=None,
                        so_luong_bom=None,
                        khac=pair_txt,
                        chi_tiet="Co o tieu diem, khong co trong don doi chieu",
                        trang_thai="❌",
                        dg_case=normalize_text(f_row.get("dg_case", "")),
                        row_kind="presence",
                    )
                )
                continue

            dvt = normalize_text(f_row["don_vi_tinh"] or o_row["don_vi_tinh"])
            f_sldm = safe_float(f_row["so_luong_dm_1"])
            o_sldm = safe_float(o_row["so_luong_dm_1"])
            f_qty_n = normalized_pm_quantity(f_row)
            o_qty_n = normalized_pm_quantity(o_row)
            sldm_ok = self.is_sldm1_match(f_sldm, o_sldm)
            qty_ok = self.is_quantity_match(dvt, f_qty_n, o_qty_n)
            ok = sldm_ok and qty_ok
            reasons = []
            if not sldm_ok:
                reasons.append("SLDM1 khac")
            if not qty_ok:
                reasons.append("So luong (chia G) khac")
            detail = "Khop tieu diem va don doi chieu" if ok else ", ".join(reasons)
            results.append(
                CompareResult(
                    ma_npl=normalize_text(f_row["ma_npl"]),
                    ten_npl=normalize_text(f_row["ten_npl"]),
                    mo_ta=normalize_text(f_row["mo_ta"]),
                    dvt=dvt,
                    sldm1_ke=f_sldm,
                    so_luong_ke=f_qty_n,
                    sldm1_bom=o_sldm,
                    so_luong_bom=o_qty_n,
                    khac=pair_txt,
                    chi_tiet=detail,
                    trang_thai="✔️" if ok else "❌",
                    dg_case=normalize_text(f_row.get("dg_case", "")),
                    row_kind="ok" if ok else "qty",
                )
            )
        return results

    def compare_pm_excel(self, ke_rows: pd.DataFrame, bom_rows: pd.DataFrame, dg_case: str) -> list[CompareResult]:
        bom_by_ma = {}
        for _, row in bom_rows.iterrows():
            bom_by_ma[normalize_key(normalize_npl_code(row["ma_npl"]))] = row

        results: list[CompareResult] = []
        for _, row in ke_rows.iterrows():
            ma_key = normalize_key(normalize_npl_code(row["ma_npl"]))
            bom_row = bom_by_ma.get(ma_key)
            if bom_row is None:
                results.append(
                    CompareResult(
                        ma_npl=normalize_npl_code(row["ma_npl"]),
                        ten_npl=normalize_text(row["ten_npl"]),
                        mo_ta=normalize_text(row["mo_ta"]),
                        dvt=normalize_text(row["don_vi_tinh"]),
                        sldm1_ke=safe_float(row["so_luong_dm_1"]),
                        so_luong_ke=safe_float(row["so_luong"]),
                        sldm1_bom=None,
                        so_luong_bom=None,
                        khac=dg_case,
                        chi_tiet=(
                            "Bang ke co ma NPL nay, Excel thieu dong "
                            "(khong tim thay tren file Excel da ket noi)."
                        ),
                        trang_thai="❌",
                        dg_case=normalize_text(row.get("dg_case", dg_case)),
                        row_kind="presence",
                    )
                )
                continue

            dvt = normalize_text(row["don_vi_tinh"])
            ke_sldm1 = safe_float(row["so_luong_dm_1"])
            # Check Excel: lay nguyen cot P bang ke, KHONG chia cot G.
            ke_qty = safe_float(row["so_luong"])
            bom_h = safe_float(bom_row["sldm1_h"])
            bom_i = safe_float(bom_row["so_luong_i"])
            bom_dvt = normalize_text(bom_row.get("dvt_excel", "")) or dvt
            qty_target = bom_i
            sldm_ok = self.is_sldm1_match(ke_sldm1, bom_h)
            qty_ok = self.is_quantity_match_excel(bom_dvt, ke_qty, qty_target)
            ok = sldm_ok and qty_ok
            detail = "Khop PM & Excel"
            if not ok:
                reasons = []
                if not sldm_ok:
                    reasons.append("Sai SLDM1 (O vs H)")
                if not qty_ok:
                    reasons.append("Sai so luong")
                detail = ", ".join(reasons)
            results.append(
                CompareResult(
                    ma_npl=normalize_npl_code(row["ma_npl"]),
                    ten_npl=normalize_text(row["ten_npl"]),
                    mo_ta=normalize_text(row["mo_ta"]),
                    dvt=bom_dvt,
                    sldm1_ke=ke_sldm1,
                    so_luong_ke=ke_qty,
                    sldm1_bom=bom_h,
                    so_luong_bom=qty_target,
                    khac=dg_case,
                    chi_tiet=detail,
                    trang_thai="✔️" if ok else "❌",
                    dg_case=normalize_text(row.get("dg_case", dg_case)),
                    row_kind="ok" if ok else ("qty" if not qty_ok else "sldm"),
                )
            )

        ke_keys = {normalize_key(normalize_npl_code(v)) for v in ke_rows["ma_npl"].tolist()}
        for _, bom_row in bom_rows.iterrows():
            key = normalize_key(normalize_npl_code(bom_row["ma_npl"]))
            if key in ke_keys:
                continue
            results.append(
                CompareResult(
                    ma_npl=normalize_npl_code(bom_row["ma_npl"]),
                    ten_npl=normalize_text(bom_row["ten_npl"]),
                    mo_ta=normalize_text(bom_row["mo_ta"]),
                    dvt=normalize_text(bom_row.get("dvt_excel", "")),
                    sldm1_ke=None,
                    so_luong_ke=None,
                    sldm1_bom=safe_float(bom_row["sldm1_h"]),
                    so_luong_bom=safe_float(bom_row["so_luong_i"]),
                    khac=dg_case,
                    chi_tiet=(
                        "Chi co trong Excel, bang ke khong co ma NPL nay "
                        "(thua dong tren file Excel / khong co trong bang ke)."
                    ),
                    trang_thai="❌",
                    dg_case=dg_case,
                    row_kind="presence",
                )
            )
        return results


class CheckBomApp:
    def __init__(self, root: tk.Tk, back_to_launcher: callable | None = None):
        self.root = root
        self.back_to_launcher = back_to_launcher
        self.root.title("Check BOM")
        self.root.geometry("1400x820")

        self.db = DatabaseManager()
        self.parser = ExcelParser(self.db)
        self.searcher = BomSearcher(self.db)
        self.comparator = BomComparator()

        self.bom_link_var = tk.StringVar()
        self.dg_case_pm_var = tk.StringVar()
        self.dg_case_excel_var = tk.StringVar()
        self.selected_customer_var = tk.StringVar()
        self.status_pm_var = tk.StringVar(value="San sang.")
        self.status_excel_var = tk.StringVar(value="San sang.")

        self.loaded_bom_ke_df: pd.DataFrame | None = None
        self.last_pm_result_df: pd.DataFrame | None = None
        self.last_excel_result_df: pd.DataFrame | None = None
        self.pm_current_subset: pd.DataFrame | None = None
        self.excel_current_subset: pd.DataFrame | None = None
        self.pm_listbox_line_to_time_key: list[str] = []
        self.last_pm_pairs: list[dict] = []
        self.excel_display_time_keys: list[str] = []
        self.excel_display_row_indexes: list[int] = []
        self.excel_pending_rows: pd.DataFrame | None = None
        self.excel_source_rows_df: pd.DataFrame | None = None
        self.excel_source_context: tuple[str, str] | None = None  # (file_path, sheet_name)
        self.excel_tree_iid_to_source_idx: dict[str, int] = {}
        self.excel_tree_iid_to_log: dict[str, str] = {}
        self._busy_count = 0
        self._busy_widgets: list[tk.Widget] = []

        self._build_ui()
        self._load_setup_data()

    def _subset_by_dg_case(self, df: pd.DataFrame, dg_case: str) -> pd.DataFrame:
        key = normalize_dg_case(dg_case)
        if not key:
            return df.iloc[0:0].copy()
        direct = df[
            df["dg_case"].map(
                lambda x: key == normalize_dg_case(x) or key in normalize_dg_case(x)
            )
        ].copy()
        if direct.empty:
            return direct
        base_product_code = normalize_text(direct.iloc[0]["product_code"])
        subset = df[df["product_code"].map(normalize_key) == normalize_key(base_product_code)].copy()
        subset = subset.sort_values(
            by=["order_date", "row_index"],
            ascending=[True, True],
            na_position="last",
        ).reset_index(drop=True)
        subset["time_key"] = subset["order_date"].map(
            lambda d: d.strftime("%Y-%m-%d") if pd.notna(d) else "N/A"
        )
        subset["time_label"] = subset["order_date"].map(
            lambda d: d.strftime("%d/%m/%Y") if pd.notna(d) else "N/A"
        )
        return subset

    def _pm_focus_rows_from_subset(self, subset: pd.DataFrame, dg_case: str) -> pd.DataFrame:
        """Tieu diem: tat ca dong bang ke trung DG Case dang tim (khong gan voi time_key)."""
        key = normalize_dg_case(dg_case)
        if not key or subset.empty:
            return subset.iloc[0:0].copy()
        mask = subset["dg_case"].map(lambda x: key == normalize_dg_case(x) or key in normalize_dg_case(x))
        return subset[mask].copy()

    def _pm_focus_row_index_set(self, focus_df: pd.DataFrame) -> set[int]:
        return {int(x) for x in focus_df["row_index"].tolist()}

    def _pm_other_time_keys(self, subset: pd.DataFrame, focus_df: pd.DataFrame) -> list[str]:
        """Cac moc time_key co it nhat mot dong nam NGOAI tieu diem (de chon lam don doi chieu)."""
        if subset.empty or focus_df.empty or "time_key" not in subset.columns:
            return []
        inside = self._pm_focus_row_index_set(focus_df)
        candidates: list[tuple[str, pd.Timestamp]] = []
        for tk, g in subset.groupby("time_key", sort=False):
            gids = {int(x) for x in g["row_index"].tolist()}
            if gids <= inside:
                continue
            od = g["order_date"].iloc[0] if len(g) else pd.Timestamp.min
            candidates.append((str(tk), od if pd.notna(od) else pd.Timestamp.min))
        candidates.sort(key=lambda x: x[1])
        return [c[0] for c in candidates]

    def _auto_pick_customer_from_subset(self, subset: pd.DataFrame) -> str:
        if subset.empty:
            return ""
        customers = self.db.get_customers()
        customer_by_code = {normalize_key(row[2]): row for row in customers if normalize_text(row[2])}
        for code in subset["customer_code"].tolist():
            mapped = customer_by_code.get(normalize_key(code))
            if mapped:
                combo_text = f"{mapped[0]} | {mapped[1]} | {mapped[2]}"
                self.selected_customer_var.set(combo_text)
                # Return folder_link, not customer code.
                return normalize_text(mapped[3])
        return ""

    def _build_ui(self) -> None:
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True)

        self.tab_setup = ttk.Frame(self.notebook, padding=10)
        self.tab_mapping = ttk.Frame(self.notebook, padding=10)
        self.tab_hash = ttk.Frame(self.notebook, padding=10)
        self.tab_check = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(self.tab_setup, text="Setup")
        self.notebook.add(self.tab_mapping, text="Ket noi Excel")
        self.notebook.add(self.tab_hash, text="Cache")
        self.notebook.add(self.tab_check, text="Check")

        self._build_tab_setup()
        self._build_tab_mapping()
        self._build_tab_hash()
        self._build_tab_check()

    def _build_tab_setup(self) -> None:
        frame_link = ttk.LabelFrame(self.tab_setup, text="Bang ke")
        frame_link.pack(fill="x", pady=(0, 10))
        ttk.Label(frame_link, text="Duong dan bang ke:").grid(row=0, column=0, sticky="w", padx=8, pady=8)
        ttk.Entry(frame_link, textvariable=self.bom_link_var, width=110).grid(
            row=0, column=1, sticky="ew", padx=8, pady=8
        )
        ttk.Button(frame_link, text="Chon file", command=self._choose_bom_link).grid(row=0, column=2, padx=8, pady=8)
        ttk.Button(frame_link, text="Luu", command=self._save_bom_link).grid(row=0, column=3, padx=8, pady=8)
        frame_link.columnconfigure(1, weight=1)

        frame_customer = ttk.LabelFrame(self.tab_setup, text="Danh sach khach hang")
        frame_customer.pack(fill="both", expand=True)
        cols = ("id", "customer_name", "code", "folder_link")
        customer_wrap = ttk.Frame(frame_customer)
        customer_wrap.pack(fill="both", expand=True, padx=8, pady=8)
        self.customer_tree = ttk.Treeview(customer_wrap, columns=cols, show="headings")
        for c, w in [("id", 60), ("customer_name", 220), ("code", 120), ("folder_link", 740)]:
            self.customer_tree.heading(c, text=c)
            self.customer_tree.column(c, width=w, anchor="w")
        y_scroll = ttk.Scrollbar(customer_wrap, orient="vertical", command=self.customer_tree.yview)
        x_scroll = ttk.Scrollbar(customer_wrap, orient="horizontal", command=self.customer_tree.xview)
        self.customer_tree.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)
        self.customer_tree.grid(row=0, column=0, sticky="nsew")
        y_scroll.grid(row=0, column=1, sticky="ns")
        x_scroll.grid(row=1, column=0, sticky="ew")
        customer_wrap.rowconfigure(0, weight=1)
        customer_wrap.columnconfigure(0, weight=1)

        btn_wrap = ttk.Frame(frame_customer)
        btn_wrap.pack(fill="x", padx=8, pady=(0, 8))
        ttk.Button(btn_wrap, text="Them", command=self._add_customer_dialog).pack(side="left")
        ttk.Button(btn_wrap, text="Sua", command=self._edit_customer_dialog).pack(side="left", padx=6)
        ttk.Button(btn_wrap, text="Xoa", command=self._delete_customer).pack(side="left")

    def _build_tab_mapping(self) -> None:
        ttk.Label(
            self.tab_mapping,
            text=(
                "Bang nay luu ket noi DG -> file/sheet/cell. Binh thuong khong can sua tay. "
                "Neu doi file BOM moi, bam 'Tai lai' hoac ket noi lai trong tab Check."
            ),
            foreground="#555555",
            wraplength=1200,
        ).pack(fill="x", pady=(0, 8))
        cols = ("dg_case", "file_path", "sheet_name", "cell", "file_hash")
        wrap = ttk.Frame(self.tab_mapping)
        wrap.pack(fill="both", expand=True)
        self.mapping_tree = ttk.Treeview(wrap, columns=cols, show="headings")
        for c, w in [
            ("dg_case", 150),
            ("file_path", 620),
            ("sheet_name", 180),
            ("cell", 90),
            ("file_hash", 280),
        ]:
            self.mapping_tree.heading(c, text=c)
            self.mapping_tree.column(c, width=w, anchor="w")
        y_scroll = ttk.Scrollbar(wrap, orient="vertical", command=self.mapping_tree.yview)
        x_scroll = ttk.Scrollbar(wrap, orient="horizontal", command=self.mapping_tree.xview)
        self.mapping_tree.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)
        self.mapping_tree.grid(row=0, column=0, sticky="nsew")
        y_scroll.grid(row=0, column=1, sticky="ns")
        x_scroll.grid(row=1, column=0, sticky="ew")
        wrap.rowconfigure(0, weight=1)
        wrap.columnconfigure(0, weight=1)
        btn_wrap = ttk.Frame(self.tab_mapping)
        btn_wrap.pack(fill="x", pady=8)
        ttk.Button(btn_wrap, text="Them mapping tay", command=self._add_mapping_dialog).pack(side="left")
        ttk.Button(btn_wrap, text="Xoa mapping chon", command=self._delete_mapping).pack(side="left", padx=6)
        ttk.Button(btn_wrap, text="Tai lai", command=self._reload_mapping_tree).pack(side="left")

    def _build_tab_hash(self) -> None:
        ttk.Label(
            self.tab_hash,
            text=(
                "Cache giup ket noi/so sanh nhanh hon. Neu du lieu nghi sai, uu tien xoa cache dong da chon "
                "roi ket noi lai. Chi xoa toan bo khi can reset hoan toan."
            ),
            foreground="#555555",
            wraplength=1200,
        ).pack(fill="x", pady=(0, 8))
        cols = ("file_path", "sheet_name", "hash_value", "last_used")
        wrap = ttk.Frame(self.tab_hash)
        wrap.pack(fill="both", expand=True)
        self.cache_tree = ttk.Treeview(wrap, columns=cols, show="headings")
        for c, w in [("file_path", 630), ("sheet_name", 220), ("hash_value", 280), ("last_used", 200)]:
            self.cache_tree.heading(c, text=c)
            self.cache_tree.column(c, width=w, anchor="w")
        y_scroll = ttk.Scrollbar(wrap, orient="vertical", command=self.cache_tree.yview)
        x_scroll = ttk.Scrollbar(wrap, orient="horizontal", command=self.cache_tree.xview)
        self.cache_tree.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)
        self.cache_tree.grid(row=0, column=0, sticky="nsew")
        y_scroll.grid(row=0, column=1, sticky="ns")
        x_scroll.grid(row=1, column=0, sticky="ew")
        wrap.rowconfigure(0, weight=1)
        wrap.columnconfigure(0, weight=1)

        btn_wrap = ttk.Frame(self.tab_hash)
        btn_wrap.pack(fill="x", pady=8)
        ttk.Button(btn_wrap, text="Tai lai", command=self._reload_cache_tree).pack(side="left")
        ttk.Button(btn_wrap, text="Xoa dong dang chon", command=self._delete_selected_cache).pack(side="left", padx=6)
        ttk.Button(btn_wrap, text="Xoa cache cu", command=self._delete_old_cache).pack(side="left", padx=6)
        ttk.Button(btn_wrap, text="Lam moi toan bo", command=self._clear_all_cache).pack(side="left")

    def _build_tab_check(self) -> None:
        self.check_notebook = ttk.Notebook(self.tab_check)
        self.check_notebook.pack(fill="both", expand=True)
        self.tab_check_pm = ttk.Frame(self.check_notebook, padding=8)
        self.tab_check_excel = ttk.Frame(self.check_notebook, padding=8)
        self.check_notebook.add(self.tab_check_pm, text="Check PM")
        self.check_notebook.add(self.tab_check_excel, text="Check Excel")
        self._build_pm_panel()
        self._build_excel_panel()

    def _build_result_tree(
        self, parent: ttk.Frame, *, compact: bool = True, include_khac: bool = True
    ) -> ttk.Treeview:
        cols = [
            "dg_case",
            "ma_npl",
            "ten_npl",
            "mo_ta",
            "dvt",
            "sldm1",
            "so_luong",
        ]
        if include_khac:
            cols.append("khac")
        cols.extend(["chi_tiet", "trang_thai"])
        tree = ttk.Treeview(parent, columns=cols, show="headings")
        if compact:
            col_defs: list[tuple[str, int, bool]] = [
                ("dg_case", 100, False),
                ("ma_npl", 120, False),
                ("ten_npl", 160, False),
                ("mo_ta", 140, False),
                ("dvt", 64, False),
                ("sldm1", 140, False),
                ("so_luong", 140, False),
                ("khac", 120, False),
                ("chi_tiet", 160, False),
                ("trang_thai", 56, False),
            ]
        else:
            col_defs = [
                ("dg_case", 220, False),
                ("ma_npl", 130, False),
                ("ten_npl", 220, True),
                ("mo_ta", 220, True),
                ("dvt", 70, False),
                ("sldm1", 170, False),
                ("so_luong", 190, False),
                ("khac", 220, False),
                ("chi_tiet", 180, True),
                ("trang_thai", 72, False),
            ]
        col_def_map = {c: (w, stretch) for c, w, stretch in col_defs}
        for c in cols:
            w, stretch = col_def_map.get(c, (120, False))
            tree.heading(c, text=c)
            anchor = "center" if c in ("dg_case", "ma_npl", "dvt", "sldm1", "so_luong", "trang_thai") else "w"
            tree.column(c, width=w, minwidth=48, stretch=stretch, anchor=anchor)
        tree.tag_configure("row_ok", background="#c8e6c9", foreground="#1b5e20")
        tree.tag_configure("row_sldm", background="#fff59d", foreground="#5d4037")
        tree.tag_configure("row_qty", background="#ffe082", foreground="#4e342e")
        tree.tag_configure("row_presence", background="#ffcdd2", foreground="#b71c1c")
        return tree

    def _build_pm_panel(self) -> None:
        top = ttk.Frame(self.tab_check_pm)
        top.pack(fill="x")
        ttk.Label(top, text="So O / DG Case:").pack(side="left", padx=(0, 6))
        self.pm_entry = ttk.Entry(top, textvariable=self.dg_case_pm_var, width=24)
        self.pm_entry.pack(side="left")
        self.pm_btn_search = ttk.Button(top, text="Tim", command=lambda: self._search_dg_rows("pm"))
        self.pm_btn_search.pack(side="left", padx=8)
        self.pm_btn_compare = ttk.Button(top, text="So sanh", command=lambda: self._start_compare_thread("pm"))
        self.pm_btn_compare.pack(side="left")
        self.pm_btn_export = ttk.Button(top, text="Export", command=lambda: self._export_result("pm"))
        self.pm_btn_export.pack(side="left", padx=6)
        if self.back_to_launcher is not None:
            ttk.Button(top, text="Back ve Launcher", command=self._back_to_launcher).pack(side="left", padx=(8, 0))

        ttk.Label(
            self.tab_check_pm,
            textvariable=self.status_pm_var,
            padding=(0, 8),
            foreground="#1f4e79",
        ).pack(fill="x")
        self.progress_pm = ttk.Progressbar(self.tab_check_pm, mode="indeterminate")
        self.progress_pm.pack(fill="x", pady=(0, 8))

        split = ttk.PanedWindow(self.tab_check_pm, orient="vertical")
        split.pack(fill="both", expand=True)
        top_list = ttk.LabelFrame(
            split,
            text=(
                "Tieu diem (dong xanh dam phia tren, luon nhin thay) = tat ca dong trung DG Case dang tim; "
                "list ben duoi chi la don doi chieu (khong co dong trong). "
                "Chon mot hoac nhieu don roi So sanh — neu khong chon thi so sanh het."
            ),
        )
        split.add(top_list, weight=1)
        focus_bar = ttk.Frame(top_list)
        focus_bar.pack(fill="x", padx=6, pady=(6, 4))
        self.pm_focus_label = ttk.Label(
            focus_bar,
            text="",
            font=("Segoe UI", 10, "bold"),
            wraplength=1100,
            anchor="nw",
            justify="left",
            foreground="#0d47a1",
        )
        self.pm_focus_label.pack(fill="x", anchor="w")
        list_row = ttk.Frame(top_list)
        list_row.pack(fill="both", expand=True, padx=6, pady=(0, 6))
        self.pm_row_listbox = tk.Listbox(list_row, selectmode="extended", exportselection=False, font=("Segoe UI", 10))
        self.pm_row_listbox.pack(side="left", fill="both", expand=True)
        pm_scroll = ttk.Scrollbar(list_row, orient="vertical", command=self.pm_row_listbox.yview)
        self.pm_row_listbox.configure(yscrollcommand=pm_scroll.set)
        pm_scroll.pack(side="right", fill="y")

        bottom_list = ttk.LabelFrame(split, text="Tong hop Check PM (double-click de mo chi tiet tung cap)")
        split.add(bottom_list, weight=2)
        wrap = ttk.Frame(bottom_list)
        wrap.pack(fill="both", expand=True, padx=6, pady=6)
        self.pm_summary_listbox = tk.Listbox(wrap, height=8, font=("Segoe UI", 10))
        self.pm_summary_listbox.pack(side="left", fill="both", expand=True)
        pm_sum_scroll = ttk.Scrollbar(wrap, orient="vertical", command=self.pm_summary_listbox.yview)
        self.pm_summary_listbox.configure(yscrollcommand=pm_sum_scroll.set)
        pm_sum_scroll.pack(side="right", fill="y")
        self.pm_summary_listbox.bind("<Double-Button-1>", self._on_pm_summary_double_click)

    def _build_excel_panel(self) -> None:
        top = ttk.Frame(self.tab_check_excel)
        top.pack(fill="x")
        ttk.Label(top, text="So O / DG Case:").pack(side="left", padx=(0, 6))
        self.excel_entry = ttk.Entry(top, textvariable=self.dg_case_excel_var, width=24)
        self.excel_entry.pack(side="left")
        ttk.Label(top, text="Khach hang:").pack(side="left", padx=(16, 6))
        self.customer_combo_excel = ttk.Combobox(
            top,
            textvariable=self.selected_customer_var,
            state="readonly",
            width=40,
        )
        self.customer_combo_excel.pack(side="left")
        self.excel_btn_connect = ttk.Button(top, text="Ket noi", command=lambda: self._search_dg_rows("excel"))
        self.excel_btn_connect.pack(side="left", padx=8)
        self.excel_btn_compare = ttk.Button(top, text="So sanh", command=lambda: self._start_compare_thread("excel"))
        self.excel_btn_compare.pack(side="left")
        self.excel_btn_export = ttk.Button(top, text="Export", command=lambda: self._export_result("excel"))
        self.excel_btn_export.pack(side="left", padx=6)
        self.excel_btn_trim = ttk.Button(top, text="Cat dong thua", command=self._trim_excel_selected_rows)
        self.excel_btn_trim.pack(side="left", padx=(8, 0))
        self.excel_btn_save_trim = ttk.Button(top, text="Luu cache cat", command=self._save_trimmed_excel_cache)
        self.excel_btn_save_trim.pack(side="left", padx=6)

        ttk.Label(
            self.tab_check_excel,
            textvariable=self.status_excel_var,
            padding=(0, 8),
            foreground="#1f4e79",
        ).pack(fill="x")
        self.progress_excel = ttk.Progressbar(self.tab_check_excel, mode="indeterminate")
        self.progress_excel.pack(fill="x", pady=(0, 8))

        bottom_list = ttk.LabelFrame(self.tab_check_excel, text="Check Excel (1 bang tong hop)")
        bottom_list.pack(fill="both", expand=True)
        wrap = ttk.Frame(bottom_list)
        wrap.pack(fill="both", expand=True, padx=6, pady=6)
        ttk.Label(
            wrap,
            text="Mau: xanh = an toan | vang = sai SLDM1 (SL khop) | cam = sai so luong | do = thieu/thua ma NPL.",
            foreground="#555555",
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 4))
        self.excel_result_tree = ttk.Treeview(
            wrap,
            columns=("ma_npl", "sldm1", "so_luong", "dvt", "chi_tiet"),
            show="headings",
            selectmode="extended",
        )
        for c, w in [("ma_npl", 240), ("sldm1", 180), ("so_luong", 200), ("dvt", 100), ("chi_tiet", 260)]:
            self.excel_result_tree.heading(c, text=c)
            self.excel_result_tree.column(c, width=w, minwidth=80, anchor="center")
        self.excel_result_tree.tag_configure("row_ok", background="#c8e6c9", foreground="#1b5e20")
        self.excel_result_tree.tag_configure("row_sldm", background="#fff59d", foreground="#5d4037")
        self.excel_result_tree.tag_configure("row_qty", background="#ffcc80", foreground="#4e342e")
        self.excel_result_tree.tag_configure("row_presence", background="#ffcdd2", foreground="#b71c1c")
        y_scroll = ttk.Scrollbar(wrap, orient="vertical", command=self.excel_result_tree.yview)
        x_scroll = ttk.Scrollbar(wrap, orient="horizontal", command=self.excel_result_tree.xview)
        self.excel_result_tree.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)
        self.excel_result_tree.grid(row=1, column=0, sticky="nsew")
        y_scroll.grid(row=1, column=1, sticky="ns")
        x_scroll.grid(row=2, column=0, sticky="ew")
        self.excel_result_tree.bind("<Double-1>", self._on_excel_row_double_click)
        wrap.rowconfigure(1, weight=1)
        wrap.columnconfigure(0, weight=1)
        self._busy_widgets = [
            self.pm_entry,
            self.pm_btn_search,
            self.pm_btn_compare,
            self.pm_btn_export,
            self.pm_row_listbox,
            self.pm_summary_listbox,
            self.excel_entry,
            self.customer_combo_excel,
            self.excel_btn_connect,
            self.excel_btn_compare,
            self.excel_btn_export,
            self.excel_btn_trim,
            self.excel_btn_save_trim,
        ]

    def _load_setup_data(self) -> None:
        self.bom_link_var.set(self.db.get_setup_value("bom_link"))
        self._reload_customer_tree()
        self._reload_mapping_tree()
        self._reload_cache_tree()

    def _choose_bom_link(self) -> None:
        path = filedialog.askopenfilename(
            title="Chon bang ke",
            filetypes=[("Excel files", "*.xlsx *.xls"), ("All files", "*.*")],
        )
        if path:
            self.bom_link_var.set(path)

    def _save_bom_link(self) -> None:
        path = self.bom_link_var.get().strip()
        if not path:
            messagebox.showwarning("Setup", "Hay nhap duong dan bang ke.")
            return
        self.db.set_setup_value("bom_link", path)
        messagebox.showinfo("Setup", "Da luu duong dan bang ke.")

    def _open_customer_dialog(
        self, title: str, customer_name: str = "", code: str = "", folder_link: str = ""
    ) -> tuple[str, str, str] | None:
        dialog = tk.Toplevel(self.root)
        dialog.title(title)
        dialog.geometry("620x220")
        dialog.transient(self.root)
        dialog.grab_set()
        name_var = tk.StringVar(value=customer_name)
        code_var = tk.StringVar(value=code)
        folder_var = tk.StringVar(value=folder_link)

        ttk.Label(dialog, text="Khach hang").grid(row=0, column=0, sticky="w", padx=10, pady=8)
        ttk.Entry(dialog, textvariable=name_var, width=55).grid(row=0, column=1, sticky="ew", padx=10, pady=8)
        ttk.Label(dialog, text="Ma").grid(row=1, column=0, sticky="w", padx=10, pady=8)
        ttk.Entry(dialog, textvariable=code_var, width=55).grid(row=1, column=1, sticky="ew", padx=10, pady=8)
        ttk.Label(dialog, text="Link thu muc").grid(row=2, column=0, sticky="w", padx=10, pady=8)
        ttk.Entry(dialog, textvariable=folder_var, width=55).grid(row=2, column=1, sticky="ew", padx=10, pady=8)
        ttk.Button(
            dialog,
            text="Chon thu muc",
            command=lambda: folder_var.set(filedialog.askdirectory(title="Chon thu muc BOM") or folder_var.get()),
        ).grid(row=2, column=2, padx=10, pady=8)
        result: dict[str, tuple[str, str, str] | None] = {"value": None}

        def submit() -> None:
            result["value"] = (name_var.get().strip(), code_var.get().strip(), folder_var.get().strip())
            dialog.destroy()

        ttk.Button(dialog, text="Luu", command=submit).grid(row=3, column=1, sticky="e", padx=10, pady=12)
        ttk.Button(dialog, text="Huy", command=dialog.destroy).grid(row=3, column=2, sticky="w", padx=10, pady=12)
        dialog.columnconfigure(1, weight=1)
        self.root.wait_window(dialog)
        return result["value"]

    def _selected_customer_id(self) -> int | None:
        sel = self.customer_tree.selection()
        if not sel:
            return None
        vals = self.customer_tree.item(sel[0], "values")
        if not vals:
            return None
        return int(vals[0])

    def _reload_customer_tree(self) -> None:
        for item in self.customer_tree.get_children():
            self.customer_tree.delete(item)
        rows = self.db.get_customers()
        combo_values = []
        for row in rows:
            self.customer_tree.insert("", "end", values=row)
            combo_values.append(f"{row[0]} | {row[1]} | {row[2]}")
        if hasattr(self, "customer_combo_excel"):
            self.customer_combo_excel["values"] = combo_values
        if combo_values and not self.selected_customer_var.get():
            self.selected_customer_var.set(combo_values[0])

    def _add_customer_dialog(self) -> None:
        result = self._open_customer_dialog("Them khach hang")
        if not result:
            return
        name, code, link = result
        if not name or not link:
            messagebox.showwarning("Khach hang", "Ten va link thu muc la bat buoc.")
            return
        self.db.add_customer(name, code, link)
        self._reload_customer_tree()

    def _edit_customer_dialog(self) -> None:
        row_id = self._selected_customer_id()
        if row_id is None:
            messagebox.showwarning("Khach hang", "Hay chon dong can sua.")
            return
        values = self.customer_tree.item(self.customer_tree.selection()[0], "values")
        result = self._open_customer_dialog(
            "Sua khach hang",
            customer_name=str(values[1]),
            code=str(values[2]),
            folder_link=str(values[3]),
        )
        if not result:
            return
        name, code, link = result
        if not name or not link:
            messagebox.showwarning("Khach hang", "Ten va link thu muc la bat buoc.")
            return
        self.db.update_customer(row_id, name, code, link)
        self._reload_customer_tree()

    def _delete_customer(self) -> None:
        row_id = self._selected_customer_id()
        if row_id is None:
            messagebox.showwarning("Khach hang", "Hay chon dong can xoa.")
            return
        if not messagebox.askyesno("Khach hang", "Xoa khach hang da chon?"):
            return
        self.db.delete_customer(row_id)
        self._reload_customer_tree()

    def _reload_mapping_tree(self) -> None:
        for item in self.mapping_tree.get_children():
            self.mapping_tree.delete(item)
        for row in self.db.get_mappings():
            self.mapping_tree.insert("", "end", values=row)

    def _add_mapping_dialog(self) -> None:
        dg_case = simpledialog.askstring("Mapping", "Nhap DG Case:")
        if not dg_case:
            return
        file_path = filedialog.askopenfilename(
            title="Chon file BOM",
            filetypes=[("Excel files", "*.xlsx *.xls"), ("All files", "*.*")],
        )
        if not file_path:
            return
        try:
            found = self.searcher.search_in_file(file_path, dg_case.strip())
            if not found:
                messagebox.showwarning("Mapping", "Khong tim thay DG Case trong file nay.")
                return
            sheet_name, cell = found
            file_hash = compute_file_signature(file_path)
            self.db.upsert_mapping(dg_case.strip(), file_path, sheet_name, cell, file_hash)
            self._reload_mapping_tree()
            messagebox.showinfo("Mapping", f"Da luu: {sheet_name} - {cell}")
        except Exception as exc:
            logging.exception("Loi add mapping")
            messagebox.showerror("Mapping", str(exc))

    def _delete_mapping(self) -> None:
        sel = self.mapping_tree.selection()
        if not sel:
            messagebox.showwarning("Mapping", "Hay chon dong mapping can xoa.")
            return
        dg_case = str(self.mapping_tree.item(sel[0], "values")[0])
        if not messagebox.askyesno("Mapping", f"Xoa mapping {dg_case}?"):
            return
        self.db.delete_mapping(dg_case)
        self._reload_mapping_tree()

    def _reload_cache_tree(self) -> None:
        for item in self.cache_tree.get_children():
            self.cache_tree.delete(item)
        for row in self.db.get_all_cache_rows():
            self.cache_tree.insert("", "end", values=row)

    def _delete_selected_cache(self) -> None:
        sel = self.cache_tree.selection()
        if not sel:
            messagebox.showwarning("Cache", "Hay chon dong cache can xoa.")
            return
        vals = self.cache_tree.item(sel[0], "values")
        if not vals:
            return
        file_path = str(vals[0])
        sheet_name = str(vals[1])
        if not messagebox.askyesno(
            "Cache",
            f"Xoa cache dang chon?\n{Path(file_path).name} | {sheet_name}",
        ):
            return
        self.db.delete_cache_entry(file_path, sheet_name)
        self._reload_cache_tree()
        self.status_excel_var.set(f"Da xoa 1 dong cache: {Path(file_path).name} | {sheet_name}")

    def _delete_old_cache(self) -> None:
        days = simpledialog.askinteger("Cache", "Xoa cache cu hon bao nhieu ngay?", initialvalue=7, minvalue=1)
        if not days:
            return
        deleted = self.db.delete_cache_older_than(days)
        self._reload_cache_tree()
        messagebox.showinfo("Cache", f"Da xoa {deleted} dong cache.")

    def _clear_all_cache(self) -> None:
        if not messagebox.askyesno("Cache", "Xoa toan bo cache?"):
            return
        self.db.clear_cache()
        self._reload_cache_tree()

    def _search_dg_rows(self, mode: str) -> None:
        try:
            dg_case = self.dg_case_pm_var.get().strip() if mode == "pm" else self.dg_case_excel_var.get().strip()
            if not dg_case:
                messagebox.showwarning("Check", "Hay nhap DG Case.")
                return
            bom_link = self.db.get_setup_value("bom_link").strip() or self.bom_link_var.get().strip()
            if not bom_link:
                messagebox.showwarning("Check", "Chua setup duong dan bang ke.")
                return
            self.loaded_bom_ke_df = self.parser.load_bom_ke(bom_link)
            subset = self._subset_by_dg_case(self.loaded_bom_ke_df, dg_case)
            if mode == "pm":
                target_listbox = self.pm_row_listbox
                target_listbox.delete(0, tk.END)
                self.pm_focus_label.config(text="")
            else:
                for item in self.excel_result_tree.get_children():
                    self.excel_result_tree.delete(item)
            if mode == "pm":
                self.last_pm_pairs = []
                self.pm_summary_listbox.delete(0, tk.END)
                self.last_pm_result_df = None
            if subset.empty:
                if mode == "pm":
                    self.status_pm_var.set("Khong tim thay dong nao theo DG Case.")
                else:
                    self.status_excel_var.set("Khong tim thay dong nao theo DG Case.")
                return

            if mode == "pm":
                self.pm_current_subset = subset.copy()
                self.pm_listbox_line_to_time_key = []
            else:
                self.excel_current_subset = subset.copy()
                self.excel_pending_rows = None
                self.excel_source_rows_df = None
                self.excel_source_context = None
                self.excel_tree_iid_to_source_idx = {}
                self.excel_display_time_keys = []
                self.excel_display_row_indexes = []

            customer_folder = self._auto_pick_customer_from_subset(subset) if mode == "excel" else ""
            excel_connect_note = ""
            if mode == "pm":
                focus_df = self._pm_focus_rows_from_subset(subset, dg_case)
                if focus_df.empty:
                    self.status_pm_var.set("Khong co dong nao trung DG Case da nhap trong cung ma san pham.")
                    return
                dg_show = normalize_text(focus_df.iloc[0]["dg_case"])
                sp_show = normalize_text(focus_df.iloc[0]["product_code"])
                focus_date = "N/A"
                if "order_date" in focus_df.columns and focus_df["order_date"].notna().any():
                    focus_date = focus_df["order_date"].dropna().iloc[0].strftime("%d/%m/%Y")
                line_focus = (
                    f"[>>> TIEU DIEM — DG dang tim]  Ngay {focus_date}  |  DG={dg_show}  |  "
                    f"{len(focus_df)} dong NPL  |  SP={sp_show}"
                )
                self.pm_focus_label.config(text=line_focus)
                other_tks = self._pm_other_time_keys(subset, focus_df)
                for time_key in other_tks:
                    gdf = subset[subset["time_key"].astype(str) == str(time_key)].copy()
                    if gdf.empty:
                        continue
                    sample = gdf.iloc[0]
                    date_value = sample["order_date"]
                    date_text = date_value.strftime("%d/%m/%Y") if pd.notna(date_value) else "N/A"
                    line = (
                        f"[don doi chieu]  Ngay {date_text}  |  DG={sample['dg_case']}  |  "
                        f"NPL={len(gdf)} dong  |  SP={sample['product_code']}"
                    )
                    target_listbox.insert(tk.END, line)
                    self.pm_listbox_line_to_time_key.append(str(time_key))
            else:
                dg_rows = subset[
                    subset["dg_case"].map(lambda x: normalize_dg_case(dg_case) in normalize_dg_case(x))
                ].copy()
                if dg_rows.empty:
                    dg_rows = subset.copy()
                self.excel_current_subset = dg_rows
                # Chi hien danh sach row sau khi "Ket noi" thanh cong.
                self.excel_pending_rows = dg_rows.copy()
                # "Ket noi" chay nen de khong khoa UI.
                if customer_folder:
                    item_code = ""
                    if "item_code" in dg_rows.columns and not dg_rows.empty:
                        item_code = normalize_text(dg_rows.iloc[0].get("item_code", ""))
                    self._start_excel_connect_thread(dg_case, customer_folder, item_code)
                    excel_connect_note = " ket noi excel - dang tim - ..."
                else:
                    excel_connect_note = " ket noi excel - that bai - chua chon khach hang"
            base_code = normalize_text(subset.iloc[0]["product_code"])
            if mode == "excel" and customer_folder:
                self.status_excel_var.set(
                    f"Da tai {len(self.excel_current_subset)} dong theo DG Case {dg_case}. "
                    f"Da auto map khach hang.{excel_connect_note}"
                )
            else:
                target_status = self.status_pm_var if mode == "pm" else self.status_excel_var
                tail = " Vui long chon customer tay." if mode == "excel" else ""
                if mode == "pm":
                    fd = self._pm_focus_rows_from_subset(subset, dg_case)
                    no = len(self._pm_other_time_keys(subset, fd))
                    target_status.set(
                        f"ket noi PM - OK - dung db. Da tai {len(subset)} dong cung ma {base_code}. "
                        f"Tieu diem: {len(fd)} dong trung DG '{dg_case}' (1 khoi duy nhat). "
                        f"{no} don khac co the chon de so sanh."
                    )
                else:
                    target_status.set(
                        f"Da tai {len(self.excel_current_subset)} dong theo DG Case {dg_case}, "
                        f"sap xep theo ngay.{tail}{excel_connect_note}"
                    )
        except Exception as exc:
            logging.exception("Loi search DG rows")
            messagebox.showerror("Check", str(exc))

    def _back_to_launcher(self) -> None:
        if self.back_to_launcher is None:
            return
        self.root.destroy()
        self.back_to_launcher()

    def _start_compare_thread(self, mode: str) -> None:
        progress = self.progress_pm if mode == "pm" else self.progress_excel
        status_var = self.status_pm_var if mode == "pm" else self.status_excel_var
        self._set_busy(True)
        progress.start(12)
        status_var.set("Dang xu ly...")
        thread = threading.Thread(target=lambda: self._run_compare(mode), daemon=True)
        thread.start()

    def _start_excel_connect_thread(self, dg_case: str, folder: str, item_code: str) -> None:
        # Background "Ket noi" to avoid freezing Tkinter UI.
        self._set_busy(True)
        self.status_excel_var.set("ket noi excel - dang tim - ...")
        thread = threading.Thread(
            target=lambda: self._run_excel_connect(dg_case, folder, item_code),
            daemon=True,
        )
        thread.start()

    def _set_busy(self, busy: bool) -> None:
        self._busy_count = self._busy_count + 1 if busy else max(0, self._busy_count - 1)
        disabled = self._busy_count > 0
        state = "disabled" if disabled else "normal"
        for w in self._busy_widgets:
            try:
                w.configure(state=state)
            except Exception:
                pass

    def _run_excel_connect(self, dg_case: str, folder: str, item_code: str) -> None:
        try:
            self.root.after(0, lambda: self.status_excel_var.set("Ket noi: tim mapping theo DG..."))
            self.root.after(0, lambda: self.status_excel_var.set("ket noi excel - dang tim - mapping theo DG"))
            file_path, sheet_name, cell = self.searcher.resolve_mapping(
                dg_case,
                folder,
                item_code=item_code,
                progress_cb=lambda msg: self.root.after(
                    0, lambda m=msg: self.status_excel_var.set(f"ket noi excel - dang tim - {m}")
                ),
            )
            self.root.after(0, lambda: self.status_excel_var.set("ket noi excel - dang tim - tai du lieu..."))
            cache_row = self.db.get_cache(file_path, sheet_name)
            cache_hit = bool(cache_row and cache_row[0] == compute_file_signature(file_path))
            bom_rows = self.parser.load_bom_sheet(file_path, sheet_name)
            self.excel_source_rows_df = bom_rows.copy()
            self.excel_source_context = (file_path, sheet_name)
            f_hash = compute_file_signature(file_path)
            # Dong bo hash mapping moi nhat de lan sau check nhanh.
            self.db.upsert_mapping(dg_case, file_path, sheet_name, cell, f_hash)
            if cache_hit:
                msg = "ket noi excel - OK - dung db"
            else:
                msg = f"ket noi excel - OK - to {Path(file_path).name}"
            self.root.after(0, lambda: self.status_excel_var.set(msg))
            self.root.after(0, lambda rows=bom_rows: self._render_excel_source_rows(rows))
        except Exception as exc:
            logging.exception("Ket noi Excel that bai")
            self.root.after(0, lambda: self.status_excel_var.set(f"ket noi excel - that bai - {exc}"))
        finally:
            self.root.after(0, self._reload_mapping_tree)
            self.root.after(0, self._reload_cache_tree)
            self.root.after(0, lambda: self._set_busy(False))

    def _render_excel_pending_rows(self) -> None:
        # Khong dung listbox nua (UI 1 bang cho Check Excel).
        return

    def _render_excel_source_rows(self, bom_rows: pd.DataFrame) -> None:
        for item in self.excel_result_tree.get_children():
            self.excel_result_tree.delete(item)
        self.excel_tree_iid_to_source_idx = {}
        self.excel_tree_iid_to_log = {}
        if bom_rows is None or bom_rows.empty:
            return
        for idx, row in bom_rows.iterrows():
            dvt = normalize_text(row.get("dvt_excel", ""))
            sldm = round_measure_value(safe_float(row.get("sldm1_h")), dvt)
            qty = round_measure_value(safe_float(row.get("so_luong_i")), dvt)
            iid = self.excel_result_tree.insert(
                "",
                "end",
                values=(
                    normalize_npl_code(row.get("ma_npl", "")),
                    "" if sldm is None else sldm,
                    "" if qty is None else qty,
                    dvt,
                    "san sang",
                ),
            )
            self.excel_tree_iid_to_source_idx[iid] = int(idx)
            self.excel_tree_iid_to_log[iid] = (
                f"ma_npl: {normalize_npl_code(row.get('ma_npl', ''))}\n"
                f"sldm1 (excel): {'' if sldm is None else sldm}\n"
                f"so_luong (excel): {'' if qty is None else qty}\n"
                f"dvt: {dvt}\n"
                "chi_tiet: san sang"
            )

    def _render_excel_compare_results(self, df: pd.DataFrame) -> None:
        for item in self.excel_result_tree.get_children():
            self.excel_result_tree.delete(item)
        self.excel_tree_iid_to_source_idx = {}
        self.excel_tree_iid_to_log = {}
        for _, row in df.iterrows():
            rk = normalize_text(row.get("row_kind", ""))
            if rk == "presence":
                tag = "row_presence"
            elif rk == "qty":
                tag = "row_qty"
            elif rk == "sldm":
                tag = "row_sldm"
            else:
                tag = "row_ok"
            dvt = normalize_text(row.get("dvt", ""))
            sldm_val = safe_float(row.get("sldm1_bom"))
            if sldm_val is None:
                sldm_val = safe_float(row.get("sldm1_ke"))
            qty_val = safe_float(row.get("so_luong_bom"))
            if qty_val is None:
                qty_val = safe_float(row.get("so_luong_ke"))
            sldm = round_measure_value(sldm_val, dvt)
            qty = round_measure_value(qty_val, dvt)
            sldm_ke = round_measure_value(safe_float(row.get("sldm1_ke")), dvt)
            qty_ke = round_measure_value(safe_float(row.get("so_luong_ke")), dvt)
            sldm_text = f"{'' if sldm is None else sldm} ({'' if sldm_ke is None else sldm_ke})"
            qty_text = f"{'' if qty is None else qty} ({'' if qty_ke is None else qty_ke})"
            detail = normalize_text(row.get("chi_tiet", ""))
            iid = self.excel_result_tree.insert(
                "",
                "end",
                values=(
                    normalize_npl_code(row.get("ma_npl", "")),
                    sldm_text,
                    qty_text,
                    dvt,
                    detail,
                ),
                tags=(tag,),
            )
            self.excel_tree_iid_to_log[iid] = (
                f"ma_npl: {normalize_npl_code(row.get('ma_npl', ''))}\n"
                f"sldm1: excel={'' if sldm is None else sldm} | bang_ke={'' if sldm_ke is None else sldm_ke}\n"
                f"so_luong: excel={'' if qty is None else qty} | bang_ke={'' if qty_ke is None else qty_ke}\n"
                f"dvt: {dvt}\n"
                f"chi_tiet: {detail}\n"
                f"trang_thai: {normalize_text(row.get('trang_thai', ''))}\n"
                f"row_kind: {normalize_text(row.get('row_kind', ''))}"
            )

    def _on_excel_row_double_click(self, event: tk.Event) -> None:
        iid = self.excel_result_tree.identify_row(event.y)
        if not iid:
            return
        body = self.excel_tree_iid_to_log.get(iid, "")
        if not body.strip():
            return
        self._show_readonly_log_dialog(self.root, "Log chi tiet dong Excel", body)

    def _trim_excel_selected_rows(self) -> None:
        if self.excel_source_rows_df is None or self.excel_source_rows_df.empty:
            messagebox.showwarning("Check", "Chua co du lieu Excel de cat.")
            return
        selected = list(self.excel_result_tree.selection())
        if not selected:
            messagebox.showwarning("Check", "Hay chon dong can cat.")
            return
        source_indexes = [self.excel_tree_iid_to_source_idx.get(iid) for iid in selected]
        source_indexes = [i for i in source_indexes if i is not None]
        if not source_indexes:
            return
        self.excel_source_rows_df = self.excel_source_rows_df.drop(index=source_indexes, errors="ignore").reset_index(drop=True)
        self._render_excel_source_rows(self.excel_source_rows_df)
        self.status_excel_var.set(
            f"Da cat {len(source_indexes)} dong. Con lai {len(self.excel_source_rows_df)} dong (chua luu cache)."
        )

    def _save_trimmed_excel_cache(self) -> None:
        if self.excel_source_rows_df is None or self.excel_source_rows_df.empty:
            messagebox.showwarning("Check", "Khong co du lieu cat de luu.")
            return
        if self.excel_source_context is None:
            messagebox.showwarning("Check", "Chua co ket noi Excel de xac dinh cache.")
            return
        file_path, sheet_name = self.excel_source_context
        cache_key = f"{sheet_name}|BOM_EXCEL_V2"
        hash_value = compute_file_signature(file_path)
        blob = pickle.dumps(self.excel_source_rows_df)
        self.db.upsert_cache(file_path, cache_key, hash_value, blob)
        self._reload_cache_tree()
        self.status_excel_var.set(
            f"Da luu cache da cat -> {Path(file_path).name} | {sheet_name} | {len(self.excel_source_rows_df)} dong."
        )

    def _current_customer_folder(self) -> str:
        selected = self.selected_customer_var.get().strip()
        if not selected:
            raise ValueError("Hay chon khach hang.")
        customer_id = int(selected.split("|", 1)[0].strip())
        for row in self.db.get_customers():
            if int(row[0]) == customer_id:
                return str(row[3])
        raise ValueError("Khong tim thay thong tin khach hang.")

    def _selected_excel_ke_rows(self) -> pd.DataFrame:
        subset = self.excel_current_subset
        if subset is None or subset.empty:
            raise ValueError("Chua tai bang ke theo DG Case.")
        return subset.copy()

    def _refresh_pm_summary_ui(self) -> None:
        self.pm_summary_listbox.delete(0, tk.END)
        for i, p in enumerate(self.last_pm_pairs):
            df = p["df"]
            if df.empty:
                n_ok = n_fail = 0
            else:
                if "row_kind" in df.columns:
                    n_ok = int((df["row_kind"] == "ok").sum())
                    n_fail = int((df["row_kind"] != "ok").sum())
                else:
                    n_ok = int((df["trang_thai"] == "✔️").sum())
                    n_fail = int((df["trang_thai"] != "✔️").sum())
            other_l = normalize_text(p.get("other_label", "")).replace("\n", " ").replace("\r", " ")
            line = (
                f"[Cap {i + 1}] Tieu diem vs {other_l}:  "
                f"khop {n_ok}  |  lech {n_fail}  |  tong {len(df)} dong  "
                f"(so luong da chia cot G bang ke)"
            ).strip()
            self.pm_summary_listbox.insert(tk.END, line)
            last_idx = self.pm_summary_listbox.size() - 1
            if n_fail == 0 and len(df) > 0:
                self.pm_summary_listbox.itemconfig(
                    last_idx, {"bg": "#c8e6c9", "fg": "#1b5e20"}
                )
            else:
                self.pm_summary_listbox.itemconfig(
                    last_idx, {"bg": "#ffcdd2", "fg": "#b71c1c"}
                )

    def _on_pm_summary_double_click(self, event: tk.Event) -> None:
        w = event.widget
        sel = w.curselection()
        if not sel:
            return
        idx = int(sel[0])
        if idx < 0 or idx >= len(self.last_pm_pairs):
            return
        self._open_pm_detail_window(idx)

    def _open_pm_detail_window(self, pair_index: int) -> None:
        if pair_index < 0 or pair_index >= len(self.last_pm_pairs):
            return
        entry = self.last_pm_pairs[pair_index]
        df = entry["df"]
        win = tk.Toplevel(self.root)
        win.title(f"Chi tiet PM — vs {entry['other_label']}")
        win.geometry("1400x720")
        wrap = ttk.Frame(win, padding=8)
        wrap.pack(fill="both", expand=True)
        ttk.Label(
            wrap,
            text=f"Tieu diem: {entry['focus_label']}  |  So voi don: {entry['other_label']}  |  Cot so luong: gia tri sau khi chia cot G bang ke.",
            wraplength=1100,
        ).pack(anchor="w", pady=(0, 4))
        ttk.Label(
            wrap,
            text="Mau: xanh = chuan | cam = lech SLDM1 / so luong | do = thieu hoac thua loai NPL. Double-click mot dong de xem log day du.",
            wraplength=1100,
            foreground="#555555",
        ).pack(anchor="w", pady=(0, 8))
        inner = ttk.Frame(wrap)
        inner.pack(fill="both", expand=True)
        tree = self._build_result_tree(inner, compact=False, include_khac=False)
        y_scroll = ttk.Scrollbar(inner, orient="vertical", command=tree.yview)
        x_scroll = ttk.Scrollbar(inner, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)
        tree.grid(row=0, column=0, sticky="nsew")
        y_scroll.grid(row=0, column=1, sticky="ns")
        x_scroll.grid(row=1, column=0, sticky="ew")
        inner.rowconfigure(0, weight=1)
        inner.columnconfigure(0, weight=1)
        la, lb = ("T", "D")
        qa, qb = ("T", "D")
        self._render_results(
            df,
            tree,
            compact=False,
            include_khac=False,
            short_measure=True,
            sldm_labels=(la, lb),
            qty_labels=(qa, qb),
        )
        win._pm_detail_row_logs = {}
        for (_, r), iid in zip(df.iterrows(), tree.get_children()):
            win._pm_detail_row_logs[iid] = format_full_row_log(r, la, lb, qa, qb)
        tree.bind(
            "<Double-1>",
            lambda e, w=win, tr=tree: self._on_pm_detail_row_double_click(e, w, tr),
        )

    def _run_compare(self, mode: str) -> None:
        pm_scheduled_success_ui = False
        try:
            dg_case = self.dg_case_pm_var.get().strip() if mode == "pm" else self.dg_case_excel_var.get().strip()
            if not dg_case:
                raise ValueError("Hay nhap DG Case.")

            if mode == "pm":
                subset = self.pm_current_subset
                if subset is None or subset.empty:
                    raise ValueError("Chua tai bang ke theo DG Case.")
                focus_df = self._pm_focus_rows_from_subset(subset, dg_case)
                if focus_df.empty:
                    raise ValueError("Khong co tieu diem (dong trung DG Case dang tim). Hay bam Tim lai.")

                picked = self.pm_row_listbox.curselection()
                other_keys: set[str] = set()
                for i in picked:
                    if 0 <= i < len(self.pm_listbox_line_to_time_key):
                        tk = self.pm_listbox_line_to_time_key[i]
                        if tk:
                            other_keys.add(str(tk))
                others_avail = self._pm_other_time_keys(subset, focus_df)
                if not other_keys:
                    if not others_avail:
                        raise ValueError(
                            "Khong co don nao khac ngoai tieu diem (tat ca dong trong ma SP deu thuoc DG dang tim)."
                        )
                    # Khong chon dong nao trong list -> so sanh tat ca don doi chieu.
                    other_keys = {str(k) for k in others_avail}

                focus_dg = normalize_text(dg_case)
                fl = f"DG {focus_dg} - {len(focus_df)} dong NPL"
                self.last_pm_pairs = []
                all_parts: list[pd.DataFrame] = []
                for ok in sorted(other_keys):
                    other_df = subset[subset["time_key"].astype(str) == ok].copy()
                    if other_df.empty:
                        continue
                    ol = normalize_text(other_df.iloc[0]["time_label"])
                    other_dg = normalize_text(other_df.iloc[0]["dg_case"])
                    pair_label = f"{focus_dg} / {other_dg}"
                    results = self.comparator.compare_pm_focus_vs_other(focus_df, other_df, fl, ol)
                    df = pd.DataFrame([r.__dict__ for r in results])
                    df["dg_case"] = pair_label
                    self.last_pm_pairs.append(
                        {"focus_label": fl, "other_label": f"{other_dg} ({ol})", "df": df, "results": results}
                    )
                    all_parts.append(df)
                self.last_pm_result_df = pd.concat(all_parts, ignore_index=True) if all_parts else pd.DataFrame()
                n_caps = len(self.last_pm_pairs)
                n_lines = len(self.last_pm_result_df)
                msg = (
                    f"Hoan tat: {n_caps} cap so sanh, tong {n_lines} dong chi tiet. "
                    f"Double-click tong hop mo bang; double-click tung dong trong bang de xem log day du."
                )

                def _pm_success_ui() -> None:
                    # Giai busy truoc refresh: Tk bo qua insert/delete tren Listbox khi state=disabled.
                    self._set_busy(False)
                    self._refresh_pm_summary_ui()
                    self.status_pm_var.set(msg)

                self.root.after(0, _pm_success_ui)
                pm_scheduled_success_ui = True
            else:
                rows = self._selected_excel_ke_rows()
                if rows.empty:
                    raise ValueError("Khong co dong du lieu de so sanh.")
                folder = self._current_customer_folder()
                item_code = ""
                if "item_code" in rows.columns:
                    item_code = normalize_text(rows.iloc[0]["item_code"])
                file_path, sheet_name, _ = self.searcher.resolve_mapping(dg_case, folder, item_code=item_code)
                # Neu user da "Cat dong thua" tren man hinh thi uu tien dung bo da cat.
                # Chi fallback parser khi chua co du lieu nguon dang hien hanh.
                if self.excel_source_rows_df is not None and not self.excel_source_rows_df.empty:
                    bom_rows = self.excel_source_rows_df.copy()
                else:
                    bom_rows = self.parser.load_bom_sheet(file_path, sheet_name)
                results = self.comparator.compare_pm_excel(rows, bom_rows, dg_case)
                out = pd.DataFrame([r.__dict__ for r in results])
                self.last_excel_result_df = out
                self.root.after(0, lambda: self._render_excel_compare_results(out))
                self.root.after(0, lambda: self.status_excel_var.set(f"Hoan tat: {len(out)} dong ket qua Excel."))
        except Exception as exc:
            logging.exception("Loi compare")
            self.root.after(0, lambda: messagebox.showerror("Check", str(exc)))
            target_status = self.status_pm_var if mode == "pm" else self.status_excel_var
            self.root.after(0, lambda: target_status.set("Co loi khi so sanh."))
        finally:
            target_progress = self.progress_pm if mode == "pm" else self.progress_excel
            self.root.after(0, target_progress.stop)
            self.root.after(0, self._reload_mapping_tree)
            self.root.after(0, self._reload_cache_tree)
            if not (mode == "pm" and pm_scheduled_success_ui):
                self.root.after(0, lambda: self._set_busy(False))

    def _render_results(
        self,
        df: pd.DataFrame,
        tree: ttk.Treeview,
        *,
        compact: bool = True,
        include_khac: bool = True,
        short_measure: bool = False,
        sldm_labels: tuple[str, str] = ("moi", "cu"),
        qty_labels: tuple[str, str] = ("moi", "cu"),
    ) -> None:
        la, lb = sldm_labels
        qa, qb = qty_labels
        max_lens = (14, 18, 24, 26, 8, 34, 36, 28, 30, 6)
        for item in tree.get_children():
            tree.delete(item)
        for _, row in df.iterrows():
            if short_measure:
                sldm_text = format_measure_pair_short(la, row["sldm1_ke"], lb, row["sldm1_bom"], row.get("dvt"))
                qty_text = format_measure_pair_short(qa, row["so_luong_ke"], qb, row["so_luong_bom"], row.get("dvt"))
            else:
                sldm_text = format_pair_cell(la, row["sldm1_ke"], lb, row["sldm1_bom"], compact=compact)
                qty_text = format_pair_cell(qa, row["so_luong_ke"], qb, row["so_luong_bom"], compact=compact)
            rk = row.get("row_kind", "")
            if rk is None or (isinstance(rk, float) and pd.isna(rk)) or str(rk).strip() == "":
                rk = infer_row_kind_from_row(row)
            else:
                rk = str(rk).strip()
            if rk == "qty":
                tag = "row_qty"
            elif rk == "sldm":
                tag = "row_sldm"
            elif rk == "presence":
                tag = "row_presence"
            else:
                tag = "row_ok"
            raw_vals = [
                row.get("dg_case", ""),
                row["ma_npl"],
                row["ten_npl"],
                row["mo_ta"],
                row["dvt"],
                sldm_text,
                qty_text,
            ]
            if include_khac:
                raw_vals.append(row["khac"])
            raw_vals.extend([
                row["chi_tiet"],
                row["trang_thai"],
            ])
            if compact:
                values = tuple(ellipsis_text(v, max_lens[i]) for i, v in enumerate(raw_vals))
            else:
                values = tuple(normalize_text(v) if v is not None else "" for v in raw_vals)
            tree.insert("", "end", values=values, tags=(tag,))

    def _on_pm_detail_row_double_click(self, event: tk.Event, win: tk.Toplevel, tree: ttk.Treeview) -> None:
        iid = tree.identify_row(event.y)
        if not iid:
            return
        body = getattr(win, "_pm_detail_row_logs", {}).get(iid, "")
        if not body.strip():
            return
        self._show_readonly_log_dialog(win, "Log day du dong", body)

    def _show_readonly_log_dialog(self, parent: tk.Toplevel, title: str, body: str) -> None:
        dlg = tk.Toplevel(parent)
        dlg.title(title)
        dlg.geometry("920x560")
        dlg.transient(parent)
        txt = scrolledtext.ScrolledText(dlg, wrap=tk.WORD, font=("Consolas", 10), height=28)
        txt.pack(fill="both", expand=True, padx=10, pady=10)
        txt.insert("1.0", body)
        txt.configure(state="disabled")
        btn = ttk.Frame(dlg)
        btn.pack(fill="x", pady=(0, 10))
        ttk.Button(btn, text="Dong", command=dlg.destroy).pack()

    def _export_result(self, mode: str) -> None:
        result_df = self.last_pm_result_df if mode == "pm" else self.last_excel_result_df
        dg_case = self.dg_case_pm_var.get().strip() if mode == "pm" else self.dg_case_excel_var.get().strip()
        if result_df is None or result_df.empty:
            messagebox.showwarning("Export", "Chua co ket qua de export.")
            return
        path = filedialog.asksaveasfilename(
            title="Luu ket qua Check BOM",
            defaultextension=".xlsx",
            filetypes=[("Excel files", "*.xlsx")],
            initialfile=f"check_bom_{mode}_{dg_case or 'result'}.xlsx",
        )
        if not path:
            return
        export_df = result_df.copy()
        export_df.to_excel(path, index=False)
        messagebox.showinfo("Export", f"Da xuat file:\n{path}")


def main(back_to_launcher: callable | None = None) -> None:
    root = tk.Tk()
    CheckBomApp(root, back_to_launcher=back_to_launcher)
    root.mainloop()


if __name__ == "__main__":
    main()

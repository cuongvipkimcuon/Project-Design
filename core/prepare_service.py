"""Prepare step — label rows from bảng kê for a planning entry."""

from __future__ import annotations

import unicodedata

import pandas as pd

from core.bom_ke_columns import NPL_QTY_ORDER
from core.utils import normalize_dg_case, normalize_text

LABEL_NPL_KEYWORDS = ("nhan", "label", "poly", "satin", "picto")


def fold_text(value: object) -> str:
    text = normalize_text(value)
    normalized = unicodedata.normalize("NFD", text)
    stripped = "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")
    return stripped.lower()


def is_label_npl_row(ten_npl: object) -> bool:
    folded = fold_text(ten_npl)
    return any(keyword in folded for keyword in LABEL_NPL_KEYWORDS)


def _row_quantity(row: pd.Series) -> float:
    """So luong NPL cho ca don hang (cot P bang ke)."""
    for key in (NPL_QTY_ORDER, "quantity"):
        if key not in row.index:
            continue
        val = row[key]
        if val is None or (isinstance(val, float) and pd.isna(val)):
            continue
        try:
            return float(val)
        except (TypeError, ValueError):
            continue
    return 0.0


def item_key(ma_npl: str, row_index: int) -> str:
    return f"{normalize_text(ma_npl)}|{int(row_index)}"


def list_label_candidates(bom_df: pd.DataFrame | None, dg_case: str) -> list[dict]:
    """Rows from bảng kê for DG Case where Tên NPL looks like a label."""
    if bom_df is None or bom_df.empty:
        return []

    key = normalize_dg_case(dg_case)
    if not key:
        return []

    mask = bom_df["dg_case"].map(
        lambda x: key == normalize_dg_case(x) or key in normalize_dg_case(x)
    )
    subset = bom_df.loc[mask]
    if subset.empty:
        return []

    out: list[dict] = []
    for _, row in subset.iterrows():
        ten_npl = normalize_text(row.get("ten_npl"))
        if not is_label_npl_row(ten_npl):
            continue
        row_index = int(row.get("row_index", 0) or 0)
        ma_npl = normalize_text(row.get("ma_npl"))
        out.append(
            {
                "row_index": row_index,
                "ma_npl": ma_npl,
                "ten_npl": ten_npl,
                "mo_ta": normalize_text(row.get("mo_ta")),
                "quantity": _row_quantity(row),
                "item_key": item_key(ma_npl, row_index),
            }
        )
    return out


def format_prepare_quantity(value: object) -> str:
    if value is None:
        return "0"
    try:
        qty = float(value)
    except (TypeError, ValueError):
        return normalize_text(value) or "0"
    if qty == int(qty):
        return str(int(qty))
    text = f"{qty:.4f}".rstrip("0").rstrip(".")
    return text or "0"

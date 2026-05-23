"""Dò nhu cầu Pictogram từ OL + bảng kê, đối chiếu tồn."""

from __future__ import annotations

from typing import Any

import pandas as pd

from core.bom_ke_columns import NPL_QTY_ORDER
from core.npl_stock_service import MODULE_PICTOGRAM, NplStockService, classify_pictogram_material
from core.utils import normalize_dg_case, normalize_text


def _row_qty(row: pd.Series) -> float:
    for key in (NPL_QTY_ORDER, "npl_qty_order", "quantity"):
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


def _bom_rows_for_so(bom_df: pd.DataFrame, ol_dg_case: str) -> pd.DataFrame:
    """OL dg_case = Số S/O (cột A bảng kê, lưu trong dg_case)."""
    key = normalize_dg_case(ol_dg_case)
    if not key:
        return bom_df.iloc[0:0]
    so_col = bom_df["dg_case"].map(normalize_dg_case)
    return bom_df.loc[so_col == key]


def check_pictogram_needs(
    ol_df: pd.DataFrame | None,
    bom_df: pd.DataFrame | None,
    stock_svc: NplStockService,
) -> dict[str, Any]:
    if ol_df is None or ol_df.empty:
        raise ValueError("Chưa có OL — vào Setup đọc OL trước.")
    if bom_df is None or bom_df.empty:
        raise ValueError("Chưa có bảng kê — vào Setup đọc bảng kê trước.")

    stock_types = stock_svc.list_types(MODULE_PICTOGRAM)
    if not stock_types:
        raise ValueError("Chưa có loại Pictogram — vào tab Pictogram thêm loại tồn trước.")

    type_order = [normalize_text(t.get("code")).upper() for t in stock_types if normalize_text(t.get("code"))]
    stock_by_code = {
        normalize_text(t.get("code")).upper(): float(t.get("balance") or 0) for t in stock_types
    }
    type_names = {
        normalize_text(t.get("code")).upper(): normalize_text(t.get("name")) for t in stock_types
    }

    dg_cases: list[str] = []
    seen: set[str] = set()
    for _, row in ol_df.iterrows():
        dg = normalize_dg_case(row.get("dg_case"))
        if not dg or dg in seen:
            continue
        seen.add(dg)
        dg_cases.append(dg)

    details: list[dict[str, Any]] = []
    missing_cases: list[str] = []
    matched_cases: list[str] = []
    cases_without_picto: list[str] = []
    type_needed: dict[str, float] = {code: 0.0 for code in type_order}

    for dg in dg_cases:
        subset = _bom_rows_for_so(bom_df, dg)
        if subset.empty:
            missing_cases.append(dg)
            continue
        matched_cases.append(dg)
        found_picto = False
        for _, brow in subset.iterrows():
            ma = normalize_text(brow.get("ma_npl"))
            type_code = classify_pictogram_material(ma, stock_types)
            if not type_code:
                continue
            found_picto = True
            qty = _row_qty(brow)
            if qty <= 0:
                continue
            tc = normalize_text(type_code).upper()
            type_needed[tc] = type_needed.get(tc, 0.0) + qty
            details.append(
                {
                    "dg_case": dg,
                    "ma_npl": ma,
                    "ten_npl": normalize_text(brow.get("ten_npl")),
                    "type_code": tc,
                    "needed": qty,
                }
            )
        if not found_picto:
            cases_without_picto.append(dg)

    by_ma: dict[str, dict[str, Any]] = {}
    for item in details:
        ma = item["ma_npl"]
        bucket = by_ma.setdefault(
            ma,
            {
                "ma_npl": ma,
                "ten_npl": item["ten_npl"],
                "type_code": item["type_code"],
                "needed": 0.0,
                "dg_case_count": 0,
                "dg_cases": [],
                "_line_qty": {},
            },
        )
        bucket["needed"] += item["needed"]
        dg = item["dg_case"]
        line_qty: dict[str, float] = bucket["_line_qty"]
        line_qty[dg] = line_qty.get(dg, 0.0) + item["needed"]
        if dg not in bucket["dg_cases"]:
            bucket["dg_cases"].append(dg)
            bucket["dg_case_count"] += 1

    summary_rows: list[dict[str, Any]] = []
    for code in type_order:
        needed = type_needed.get(code, 0.0)
        stock = stock_by_code.get(code, 0.0)
        summary_rows.append(
            {
                "type_code": code,
                "type_name": type_names.get(code, code),
                "needed": needed,
                "stock": stock,
                "print": max(0.0, needed - stock),
            }
        )

    aggregated = sorted(by_ma.values(), key=lambda x: (-x["needed"], x["ma_npl"]))
    for item in aggregated:
        line_qty: dict[str, float] = item.pop("_line_qty", {})
        item["line_items"] = [
            {"dg_case": dg, "needed": qty}
            for dg, qty in sorted(line_qty.items(), key=lambda x: (-x[1], x[0]))
        ]
    for item in aggregated:
        tc = normalize_text(item.get("type_code")).upper()
        stock = stock_by_code.get(tc, 0.0)
        item["stock_type"] = stock
        type_total = type_needed.get(tc, 0.0)
        type_print = max(0.0, type_total - stock)
        if type_total > 0:
            share = item["needed"] / type_total
            item["print_share"] = round(type_print * share, 2)
        else:
            item["print_share"] = max(0.0, item["needed"] - stock)

    tracked_codes = ", ".join(type_order[:8])
    if len(type_order) > 8:
        tracked_codes += "…"

    return {
        "ol_dg_count": len(dg_cases),
        "matched_bom_count": len(matched_cases),
        "cases_with_picto_count": len(matched_cases) - len(cases_without_picto),
        "tracked_type_codes": type_order,
        "tracked_codes_label": tracked_codes,
        "summary": summary_rows,
        "all_details": aggregated,
        "details": aggregated,
        "missing_bom_cases": missing_cases,
        "cases_without_picto": cases_without_picto,
        "detail_line_count": len(details),
    }


def pictogram_ma_key(ma_npl: str) -> str:
    return normalize_text(ma_npl).upper()


def apply_pictogram_exclusions(
    result: dict[str, Any],
    excluded_ma: set[str] | frozenset[str] | None = None,
) -> dict[str, Any]:
    """Loại mã NPL khỏi tổng Check — giữ nguyên danh sách gốc trong all_details."""
    excluded = {normalize_text(m).upper() for m in (excluded_ma or set()) if normalize_text(m)}
    type_order = list(result.get("tracked_type_codes") or [])
    stock_by_code = {
        normalize_text(item.get("type_code")).upper(): float(item.get("stock") or 0)
        for item in (result.get("summary") or [])
    }
    type_names = {
        normalize_text(item.get("type_code")).upper(): normalize_text(item.get("type_name"))
        for item in (result.get("summary") or [])
    }
    all_details = list(result.get("all_details") or result.get("details") or [])

    active_details: list[dict[str, Any]] = []
    type_needed: dict[str, float] = {code: 0.0 for code in type_order}
    for item in all_details:
        ma_key = pictogram_ma_key(item.get("ma_npl", ""))
        copy = dict(item)
        copy["excluded"] = ma_key in excluded
        active_details.append(copy)
        if copy["excluded"]:
            continue
        tc = normalize_text(copy.get("type_code")).upper()
        type_needed[tc] = type_needed.get(tc, 0.0) + float(copy.get("needed") or 0)

    summary_rows: list[dict[str, Any]] = []
    for code in type_order:
        needed = type_needed.get(code, 0.0)
        stock = stock_by_code.get(code, 0.0)
        summary_rows.append(
            {
                "type_code": code,
                "type_name": type_names.get(code, code),
                "needed": needed,
                "stock": stock,
                "print": max(0.0, needed - stock),
            }
        )

    for item in active_details:
        if item.get("excluded"):
            item["print_share"] = 0.0
            continue
        tc = normalize_text(item.get("type_code")).upper()
        stock = stock_by_code.get(tc, 0.0)
        item["stock_type"] = stock
        type_total = type_needed.get(tc, 0.0)
        type_print = max(0.0, type_total - stock)
        needed = float(item.get("needed") or 0)
        if type_total > 0:
            item["print_share"] = round(type_print * (needed / type_total), 2)
        else:
            item["print_share"] = max(0.0, needed - stock)

    active_count = sum(1 for item in active_details if not item.get("excluded"))
    return {
        **result,
        "all_details": all_details,
        "details": active_details,
        "summary": summary_rows,
        "excluded_ma_count": len(excluded),
        "active_detail_count": active_count,
    }

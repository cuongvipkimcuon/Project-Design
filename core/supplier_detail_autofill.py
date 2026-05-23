"""Gợi ý cột Detail khi tạo phiếu Supplier."""

from __future__ import annotations

from typing import Any

import pandas as pd

from core.database import HubDatabase
from core.emg_scanner_reader import lookup_uniform_serial
from core.supplier_detail_rules import (
    DEFAULT_PICTO_SIZE_CM,
    EMG_SERIAL_SCAN_LIMIT,
    apply_custom_rule,
    find_custom_rule,
    load_detail_rules,
)
from core.utils import normalize_text

DETAIL_704 = "Check Poly or Satin"


def _material_prefix(material_code: str) -> str:
    return normalize_text(material_code).replace(" ", "")


def _builtin_detail(
    material_code: str,
    dg_case: str,
    *,
    db: HubDatabase | None = None,
) -> str:
    mat = _material_prefix(material_code)
    if not mat:
        return ""

    if mat.startswith("705"):
        return lookup_uniform_serial(dg_case, db=db, limit=EMG_SERIAL_SCAN_LIMIT)

    if mat.startswith("704"):
        return DETAIL_704

    if mat.startswith("720"):
        return _pictogram_detail(mat, DEFAULT_PICTO_SIZE_CM)

    return ""


def _pictogram_detail(material_code: str, size_map: dict[str, int]) -> str:
    parts = [p for p in material_code.split(".") if p]
    if not parts:
        return ""
    suffix = parts[-1].upper()
    if len(suffix) != 1:
        return ""
    cm = size_map.get(suffix)
    if cm is None:
        return ""
    return f"Pictogram size {suffix} ({cm}cm)"


def suggest_slip_line_detail(
    material_code: str,
    dg_case: str,
    *,
    db: HubDatabase | None = None,
    ol_df: pd.DataFrame | None = None,
    bom_df: pd.DataFrame | None = None,
    line: dict[str, Any] | None = None,
) -> str:
    if db is None:
        return _builtin_detail(material_code, dg_case, db=db)

    rules = load_detail_rules(db)
    base_line = line or {"material_code": material_code, "dg_case": dg_case}
    custom = find_custom_rule(
        material_code,
        rules,
        line=base_line,
        db=db,
        ol_df=ol_df,
        bom_df=bom_df,
    )
    if custom:
        return apply_custom_rule(
            custom,
            material_code,
            dg_case,
            db=db,
            ol_df=ol_df,
            bom_df=bom_df,
            line=line,
        )

    return _builtin_detail(material_code, dg_case, db=db)


def apply_detail_autofill(
    line: dict[str, Any],
    *,
    db: HubDatabase | None = None,
    ol_df: pd.DataFrame | None = None,
    bom_df: pd.DataFrame | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    if not overwrite and normalize_text(line.get("detail")):
        return line
    detail = suggest_slip_line_detail(
        normalize_text(line.get("material_code")),
        normalize_text(line.get("dg_case")),
        db=db,
        ol_df=ol_df,
        bom_df=bom_df,
        line=line,
    )
    if detail:
        line = dict(line)
        line["detail"] = detail
    return line


def apply_detail_autofill_lines(
    lines: list[dict[str, Any]],
    *,
    db: HubDatabase | None = None,
    ol_df: pd.DataFrame | None = None,
    bom_df: pd.DataFrame | None = None,
    overwrite: bool = False,
) -> list[dict[str, Any]]:
    return [
        apply_detail_autofill(line, db=db, ol_df=ol_df, bom_df=bom_df, overwrite=overwrite)
        for line in lines
    ]

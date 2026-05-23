"""Tra customer / mã khách theo DG Case."""

from __future__ import annotations

from typing import Any

import pandas as pd

from core.database import HubDatabase
from core.emg_scanner_reader import lookup_customer_for_dg_case
from core.ol_reader import OlReaderService
from core.utils import normalize_dg_case, normalize_text


def _first_nonempty(df: pd.DataFrame, column: str) -> str:
    if df.empty or column not in df.columns:
        return ""
    for val in df[column]:
        text = normalize_text(val)
        if text:
            return text
    return ""


def lookup_customer_by_dg_case(
    dg_case: str,
    *,
    db: HubDatabase | None = None,
    ol_df: pd.DataFrame | None = None,
    bom_df: pd.DataFrame | None = None,
) -> dict[str, str]:
    """
    Tra customer khi biết DG Case.
    Thứ tự: OL → bảng kê → EMG scanner.
    """
    key = normalize_dg_case(dg_case)
    empty = {"customer": "", "customer_code": "", "source": ""}
    if not key:
        return empty

    ol_service = OlReaderService(db) if db else OlReaderService()

    if ol_df is not None and not ol_df.empty:
        matches = ol_service.find_by_dg_case(ol_df, key)
        if not matches.empty:
            customer = _first_nonempty(matches, "customer")
            customer_code = _first_nonempty(matches, "customer_code")
            if customer or customer_code:
                return {
                    "customer": customer,
                    "customer_code": customer_code,
                    "source": "ol",
                }

    if bom_df is not None and not bom_df.empty and "dg_case" in bom_df.columns:
        mask = bom_df["dg_case"].map(
            lambda x: key == normalize_dg_case(x) or key in normalize_dg_case(x)
        )
        subset = bom_df.loc[mask]
        if not subset.empty:
            customer_code = _first_nonempty(subset, "customer_code")
            if customer_code:
                return {
                    "customer": customer_code,
                    "customer_code": customer_code,
                    "source": "bom_ke",
                }

    emg_customer = lookup_customer_for_dg_case(key, db=db)
    if emg_customer:
        return {
            "customer": emg_customer,
            "customer_code": emg_customer,
            "source": "emg_scanner",
        }

    return empty


def customer_context_for_line(
    line: dict[str, Any],
    *,
    db: HubDatabase | None = None,
    ol_df: pd.DataFrame | None = None,
    bom_df: pd.DataFrame | None = None,
) -> dict[str, str]:
    dg = normalize_text(line.get("dg_case"))
    info = lookup_customer_by_dg_case(dg, db=db, ol_df=ol_df, bom_df=bom_df)
    product_code = normalize_text(line.get("product_code"))
    production_no = product_code

    logo = normalize_text(line.get("logo"))

    if ol_df is not None and not ol_df.empty and dg:
        ol_service = OlReaderService(db) if db else OlReaderService()
        matches = ol_service.find_by_dg_case(ol_df, normalize_dg_case(dg))
        if not matches.empty:
            ol_prod = _first_nonempty(matches, "production_no")
            if ol_prod:
                production_no = ol_prod
            if not logo:
                logo = _first_nonempty(matches, "logo")

    return {
        "customer": info.get("customer", ""),
        "customer_code": info.get("customer_code", ""),
        "dg_case": dg,
        "material": normalize_text(line.get("material_code")),
        "product_code": product_code,
        "production_no": production_no,
        "logo": logo,
    }

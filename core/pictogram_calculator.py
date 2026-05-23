"""Tính số lượng tem Pictogram — logic sheet «1 (6)» trong pictogram calculator.xlsx."""

from __future__ import annotations

import math
from typing import Any

from core.npl_stock_service import DEFAULT_PICTOGRAM_CODES
from core.supplier_detail_rules import DEFAULT_PICTO_SIZE_CM
from core.utils import normalize_text

FABRIC_WIDTH_CM = 145
PICTO_SIZE_SUFFIXES = ("S", "M", "L")
PICTO_LABEL_TYPES = DEFAULT_PICTOGRAM_CODES


def pictogram_cm(size: str, size_map: dict[str, int] | None = None) -> int:
    key = normalize_text(size).upper()
    mapping = size_map or DEFAULT_PICTO_SIZE_CM
    if key == "L":
        return int(mapping.get("L", 17))
    if key == "M":
        return int(mapping.get("M", 12))
    return int(mapping.get("S", 10))


def labels_per_row(cm: int) -> int:
    if cm <= 0:
        return 0
    return int(FABRIC_WIDTH_CM / cm)


def infer_size_from_ma_npl(ma_npl: str) -> str:
    parts = [p for p in normalize_text(ma_npl).replace(" ", "").split(".") if p]
    if not parts:
        return ""
    suffix = parts[-1].upper()
    return suffix if suffix in PICTO_SIZE_SUFFIXES else ""


def pictogram_cm_from_type_code(type_code: str, size_map: dict[str, int] | None = None) -> int:
    """S/M/L hoặc mã dài (720.176.USA.S) → cm tem theo size cuối."""
    key = normalize_text(type_code).upper()
    if key in PICTO_SIZE_SUFFIXES:
        return pictogram_cm(key, size_map)
    suffix = infer_size_from_ma_npl(key)
    if suffix in PICTO_SIZE_SUFFIXES:
        return pictogram_cm(suffix, size_map)
    return pictogram_cm("S", size_map)


def calculate_pictogram_fabric(
    type_quantities: dict[str, float],
    *,
    label_types: list[str] | None = None,
    size_map: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Tính hàng in + mét vải từ số lượng tem theo loại đang theo dõi."""
    codes = label_types or sorted(type_quantities.keys()) or list(PICTO_LABEL_TYPES)
    rows: list[dict[str, Any]] = []
    fabric_total = 0.0
    for label_type in codes:
        key = normalize_text(label_type).upper()
        try:
            qty = float(type_quantities.get(key, type_quantities.get(label_type)) or 0)
        except (TypeError, ValueError):
            qty = 0.0
        if qty < 0:
            qty = 0.0
        cm = pictogram_cm_from_type_code(key, size_map)
        per_row = labels_per_row(cm)
        min_rows = math.ceil(qty / per_row) if per_row > 0 and qty > 0 else 0
        actual = min_rows * per_row if per_row > 0 else 0
        fabric_m = (min_rows * cm / 100.0) if min_rows > 0 else 0.0
        fabric_total += fabric_m
        rows.append(
            {
                "label_type": key,
                "qty": qty,
                "cm": cm,
                "labels_per_row": per_row,
                "min_rows": min_rows,
                "actual_labels": actual,
                "fabric_m": fabric_m,
            }
        )
    return {"rows": rows, "fabric_total_m": fabric_total}

"""Đọc emg_scanner_export.json — tra serial theo DG Case (scan_type IN)."""

from __future__ import annotations

import json
from pathlib import Path

from core.paths import app_dir
from core.utils import normalize_dg_case, normalize_text

_CACHE: dict[str, tuple[float, dict[str, list[str]]]] = {}


def clear_emg_cache() -> None:
    _CACHE.clear()


def _index_path(path: Path) -> dict[str, list[str]]:
    mtime = path.stat().st_mtime
    key = str(path.resolve())
    cached = _CACHE.get(key)
    if cached and cached[0] == mtime:
        return cached[1]

    data = json.loads(path.read_text(encoding="utf-8"))
    by_case: dict[str, list[str]] = {}
    for scan in data.get("scans") or []:
        if normalize_text(scan.get("scan_type")).upper() != "IN":
            continue
        case = normalize_dg_case(scan.get("case_no"))
        if not case:
            continue
        serial = normalize_text(scan.get("serial"))
        by_case.setdefault(case, []).append(serial)

    _CACHE[key] = (mtime, by_case)
    return by_case


def resolve_emg_scanner_path(db=None) -> Path | None:
    default = app_dir() / "emg_scanner_export.json"
    raw = ""
    if db is not None:
        raw = normalize_text(db.get_setup("emg_scanner_json_path", ""))
    path = Path(raw) if raw else default
    return path if path.is_file() else None


def lookup_uniform_serial(
    dg_case: str,
    *,
    db=None,
    limit: int = 10,
) -> str:
    """
    Lấy tối đa `limit` bản ghi IN theo case_no.
    Nếu mọi serial (không rỗng) giống nhau → trả serial đó.
    """
    path = resolve_emg_scanner_path(db)
    if not path:
        return ""

    key = normalize_dg_case(dg_case)
    if not key:
        return ""

    rows = _index_path(path).get(key, [])[: max(1, limit)]
    serials = [s for s in rows if s]
    if not serials:
        return ""

    first = serials[0]
    if all(s == first for s in serials):
        return first
    return ""


def lookup_customer_for_dg_case(
    dg_case: str,
    *,
    db=None,
    limit: int = 10,
) -> str:
    """Customer từ EMG (case_no, scan_type IN)."""
    path = resolve_emg_scanner_path(db)
    if not path:
        return ""

    key = normalize_dg_case(dg_case)
    if not key:
        return ""

    data = json.loads(path.read_text(encoding="utf-8"))
    seen: list[str] = []
    for scan in data.get("scans") or []:
        if normalize_text(scan.get("scan_type")).upper() != "IN":
            continue
        if normalize_dg_case(scan.get("case_no")) != key:
            continue
        customer = normalize_text(scan.get("customer"))
        if customer:
            seen.append(customer)
        if len(seen) >= max(1, limit):
            break
    if not seen:
        return ""
    return seen[0]

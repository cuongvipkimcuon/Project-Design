"""Planning calendar helpers — validation and date normalization."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

from core.utils import format_date_dd_mm_yyyy, normalize_dg_case, normalize_text, parse_date_dd_mm_yyyy

DEFAULT_EXCEL_MAP = {
    "dg_case": "A",
    "item_code": "B",
    "supplier": "C",
    "quantity": "D",
    "plan_date": "E",
    "verify_date": "F",
    "session": "G",
    "start_row": "2",
}


class PlanningValidationError(ValueError):
    pass


def col_ref_to_index(value: str) -> int:
    text = normalize_text(value).upper()
    if not text:
        raise PlanningValidationError("Column reference cannot be empty.")
    if text.isdigit():
        idx = int(text) - 1
        if idx < 0:
            raise PlanningValidationError("Column number must be >= 1.")
        return idx
    idx = 0
    for ch in text:
        if not ("A" <= ch <= "Z"):
            raise PlanningValidationError(f"Invalid column reference: {value}")
        idx = idx * 26 + (ord(ch) - ord("A") + 1)
    return idx - 1


def cell_to_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and pd.isna(value):
        return ""
    if isinstance(value, pd.Timestamp):
        if pd.isna(value):
            return ""
        return format_date_dd_mm_yyyy(value.to_pydatetime())
    if isinstance(value, (datetime, date)):
        return format_date_dd_mm_yyyy(value)
    return normalize_text(value)


def parse_display_date(value: object, field_name: str, *, required: bool = True) -> tuple[str, str]:
    text = cell_to_text(value)
    if not text:
        if not required:
            return "", ""
        raise PlanningValidationError(f"{field_name} is required (dd-mm-yyyy).")
    parsed = parse_date_dd_mm_yyyy(text)
    if parsed is None:
        raise PlanningValidationError(f"{field_name} must be dd-mm-yyyy.")
    return format_date_dd_mm_yyyy(parsed), parsed.strftime("%Y-%m-%d")


def normalize_session(value: object) -> str:
    text = cell_to_text(value)
    if not text or text in {"—", "-", "None"}:
        return ""
    low = text.lower()
    if low in {"morning", "am", "sáng", "sang"}:
        return "Morning"
    if low in {"afternoon", "pm", "chiều", "chieu"}:
        return "Afternoon"
    if text in {"Morning", "Afternoon"}:
        return text
    raise PlanningValidationError("Session must be Morning, Afternoon, or left blank.")


def validate_plan_payload(
    *,
    dg_case: object,
    item_code: object,
    quantity: object,
    plan_date: object,
    verify_date: object,
    session: object = "",
    supplier: object = "",
) -> dict[str, object]:
    dg = normalize_dg_case(cell_to_text(dg_case))
    if not dg:
        raise PlanningValidationError("DG Case is required.")

    item = normalize_text(cell_to_text(item_code))
    if not item:
        raise PlanningValidationError("Production No is required.")

    supplier_text = normalize_text(cell_to_text(supplier))
    if not supplier_text:
        raise PlanningValidationError("Supplier is required.")

    qty_text = normalize_text(cell_to_text(quantity)).replace(",", ".")
    if not qty_text:
        raise PlanningValidationError("Quantity is required.")
    try:
        qty = float(qty_text)
    except ValueError as exc:
        raise PlanningValidationError("Quantity must be a number.") from exc
    if qty < 0:
        raise PlanningValidationError("Quantity cannot be negative.")

    plan_display, plan_iso = parse_display_date(plan_date, "Hạn giao tem", required=False)
    verify_raw = cell_to_text(verify_date)
    if not verify_raw:
        verify_display = format_date_dd_mm_yyyy(date.today())
        verify_iso = date.today().strftime("%Y-%m-%d")
    else:
        verify_display, verify_iso = parse_display_date(verify_date, "Ngày lập KH")
    session_norm = normalize_session(session)

    return {
        "dg_case": dg,
        "item_code": item,
        "supplier": supplier_text,
        "quantity": qty,
        "plan_date": plan_display,
        "plan_date_iso": plan_iso,
        "verify_date": verify_display,
        "verify_date_iso": verify_iso,
        "session": session_norm,
    }


def load_excel_mapping(db) -> dict[str, str]:
    out = dict(DEFAULT_EXCEL_MAP)
    for key in DEFAULT_EXCEL_MAP:
        saved = db.get_setup(f"planning_xls_{key}", "")
        if saved:
            out[key] = saved
    return out


def save_excel_mapping(db, mapping: dict[str, str]) -> None:
    for key, value in mapping.items():
        db.set_setup(f"planning_xls_{key}", normalize_text(value))


def import_plans_from_excel(file_path: str, mapping: dict[str, str]) -> tuple[list[dict], list[str]]:
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    start_row = int(normalize_text(mapping.get("start_row", "2")) or "2")
    if start_row < 1:
        raise PlanningValidationError("Start row must be >= 1.")

    df = pd.read_excel(path, sheet_name=0, header=None)
    if df.empty:
        raise PlanningValidationError("Excel file is empty.")

    cols = {
        "dg_case": col_ref_to_index(mapping["dg_case"]),
        "item_code": col_ref_to_index(mapping["item_code"]),
        "supplier": col_ref_to_index(mapping["supplier"]),
        "quantity": col_ref_to_index(mapping["quantity"]),
        "plan_date": col_ref_to_index(mapping["plan_date"]),
        "verify_date": col_ref_to_index(mapping["verify_date"]),
    }
    session_col = normalize_text(mapping.get("session", ""))
    session_idx = col_ref_to_index(session_col) if session_col else None

    plans: list[dict] = []
    errors: list[str] = []
    for row_idx in range(start_row - 1, len(df)):
        row = df.iloc[row_idx]
        if all(cell_to_text(row.iloc[i]) == "" for i in cols.values() if i < len(row)):
            continue
        try:
            payload = validate_plan_payload(
                dg_case=row.iloc[cols["dg_case"]] if cols["dg_case"] < len(row) else "",
                item_code=row.iloc[cols["item_code"]] if cols["item_code"] < len(row) else "",
                supplier=row.iloc[cols["supplier"]] if cols["supplier"] < len(row) else "",
                quantity=row.iloc[cols["quantity"]] if cols["quantity"] < len(row) else "",
                plan_date=row.iloc[cols["plan_date"]] if cols["plan_date"] < len(row) else "",
                verify_date=row.iloc[cols["verify_date"]] if cols["verify_date"] < len(row) else "",
                session=row.iloc[session_idx] if session_idx is not None and session_idx < len(row) else "",
            )
            plans.append(payload)
        except PlanningValidationError as exc:
            errors.append(f"Row {row_idx + 1}: {exc}")

    if not plans and errors:
        raise PlanningValidationError("\n".join(errors[:8]))
    return plans, errors


def session_badge(session: str) -> str:
    if session == "Morning":
        return "AM"
    if session == "Afternoon":
        return "PM"
    return ""


def iso_today() -> str:
    return date.today().strftime("%Y-%m-%d")


def iso_in_days(days: int) -> str:
    return (date.today() + timedelta(days=days)).strftime("%Y-%m-%d")


def plan_needs_delivery_date(plan: dict) -> bool:
    if normalize_text(plan.get("check_status")) == "confirmed":
        return False
    return not normalize_text(plan.get("plan_date_iso"))


def effective_check_status(plan: dict, *, today_iso: str | None = None) -> str:
    stored = normalize_text(plan.get("check_status")) or "pending"
    if stored == "confirmed":
        return "confirmed"
    if stored == "miss":
        return "miss"
    if plan_needs_delivery_date(plan):
        return "no_date"
    ref = today_iso or iso_today()
    plan_iso = normalize_text(plan.get("plan_date_iso"))
    if plan_iso and plan_iso <= ref:
        return "miss"
    return "pending"


def effective_prepare_status(plan: dict) -> str:
    stored = normalize_text(plan.get("prepare_status")) or "pending"
    return "prepared" if stored == "prepared" else "pending"


def check_status_label(status: str) -> str:
    return {
        "confirmed": "Đã lưu",
        "miss": "Miss",
        "no_date": "Chưa có hạn giao",
        "pending": "Chưa lưu",
    }.get(status, status.title())


def prepare_status_label(status: str) -> str:
    return "Prepared" if status == "prepared" else "Pending"


def format_plan_date_display(plan: dict) -> str:
    text = normalize_text(plan.get("plan_date"))
    return text or "—"


def format_check_display(plan: dict) -> str:
    status = effective_check_status(plan)
    label = check_status_label(status)
    by = normalize_text(plan.get("check_by"))
    if status == "confirmed" and by:
        return f"{label}\n{by}"
    return label


def format_check_timestamp(value: object) -> str:
    text = normalize_text(value)
    if not text:
        return ""
    try:
        dt = datetime.fromisoformat(text)
        return dt.strftime("%d-%m-%Y %H:%M:%S")
    except ValueError:
        return text


def format_prepare_display(plan: dict) -> str:
    status = effective_prepare_status(plan)
    if status == "prepared":
        by = normalize_text(plan.get("prepare_by"))
        return by or prepare_status_label(status)
    return prepare_status_label(status)


PLANNING_AUDIT_ACTIONS = {
    "created": "Tạo plan",
    "updated": "Cập nhật",
    "deleted": "Xóa",
    "check_confirmed": "Đã lưu tem",
    "prepared": "Prepare",
}


def plan_snapshot(entry: dict) -> dict[str, object]:
    return {
        "dg_case": normalize_text(entry.get("dg_case")),
        "item_code": normalize_text(entry.get("item_code")),
        "supplier": normalize_text(entry.get("supplier")),
        "quantity": entry.get("quantity"),
        "plan_date": normalize_text(entry.get("plan_date")),
        "plan_date_iso": normalize_text(entry.get("plan_date_iso")),
        "verify_date": normalize_text(entry.get("verify_date")),
        "verify_date_iso": normalize_text(entry.get("verify_date_iso")),
        "session": normalize_text(entry.get("session")),
    }


def format_plan_change_line(detail: dict) -> str:
    before = detail.get("before") or {}
    after = detail.get("after") or {}
    if not before and not after:
        return ""
    parts: list[str] = []
    labels = {
        "plan_date": "Hạn giao tem",
        "verify_date": "Ngày lập KH",
        "dg_case": "DG Case",
        "item_code": "Production No",
        "supplier": "Supplier",
        "quantity": "Qty",
        "session": "Session",
    }
    for key, label in labels.items():
        old = before.get(key)
        new = after.get(key)
        if old != new and (old or new):
            parts.append(f"{label}: {old or '—'} → {new or '—'}")
    return " · ".join(parts)


def audit_action_label(action: str) -> str:
    return PLANNING_AUDIT_ACTIONS.get(action, action.replace("_", " ").title())


def format_audit_log_line(entry: dict) -> str:
    when = format_check_timestamp(entry.get("created_at"))
    action = audit_action_label(str(entry.get("action", "")))
    dg = normalize_text(entry.get("dg_case")) or "—"
    item = normalize_text(entry.get("item_code")) or "—"
    supplier = normalize_text(entry.get("supplier")) or "—"
    plan_date = normalize_text(entry.get("plan_date")) or "—"
    verify_date = normalize_text(entry.get("verify_date")) or "—"
    actor = normalize_text(entry.get("actor")) or "—"
    line = f"{when} · {action} · {dg} · {item} · {supplier} · Giao {plan_date} · Lập KH {verify_date} · {actor}"
    detail = entry.get("detail")
    change = format_plan_change_line(detail if isinstance(detail, dict) else {})
    if change:
        line += f"\n    {change}"
    return line


def describe_duplicate_plan(plan: dict) -> str:
    return (
        f"DG Case {plan.get('dg_case')} · Hạn giao {plan.get('plan_date')} · "
        f"Ngày lập KH {plan.get('verify_date')} · {plan.get('item_code')}"
    )


def day_has_miss(plans: list[dict], *, today_iso: str | None = None) -> bool:
    return any(effective_check_status(p, today_iso=today_iso) == "miss" for p in plans)


def day_all_confirmed(plans: list[dict]) -> bool:
    return bool(plans) and all(effective_check_status(p) == "confirmed" for p in plans)

"""Supplier slip — tạo từ plan chưa check, OL logo/color, export."""

from __future__ import annotations

from typing import Any

import pandas as pd

from core import supplier_db
from core.database import HubDatabase
from core.ol_reader import OlReaderService
from core.planning_service import effective_check_status, effective_prepare_status
from core.prepare_service import list_label_candidates
from core.supplier_detail_autofill import apply_detail_autofill_lines
from core.utils import format_date_dd_mm_yyyy, normalize_dg_case, normalize_text

DEFAULT_REASON = "giao lần đầu"


def slip_status_label(status: str) -> str:
    return "Done" if status == "done" else "Pending"


def display_check_date(slip: dict) -> str:
    """Cột Date trên list = ngày check (không phải ngày tạo)."""
    if normalize_text(slip.get("status")) != "done":
        return "—"
    raw = normalize_text(slip.get("checked_at"))
    if not raw:
        return "—"
    try:
        from datetime import datetime

        dt = datetime.fromisoformat(raw.replace("Z", ""))
        return format_date_dd_mm_yyyy(dt)
    except ValueError:
        return raw[:10]


def build_line_from_plan(
    db: HubDatabase,
    plan: dict,
    *,
    ol_df: pd.DataFrame | None,
    bom_df: pd.DataFrame | None,
    line_no: int,
    prepare_row: dict | None = None,
) -> dict[str, Any]:
    dg = normalize_text(plan.get("dg_case"))
    product = normalize_text(plan.get("item_code"))
    color = ""
    logo = ""
    material = ""
    qty = float(plan.get("quantity") or 0)

    if ol_df is not None and not ol_df.empty:
        ol = OlReaderService(db).lookup_fields_for_dg_case(ol_df, dg)
        color = ol.get("color", "")
        logo = ol.get("logo", "")
        if not product:
            product = ol.get("item_code") or ol.get("production_no", "")

    if prepare_row:
        material = normalize_text(prepare_row.get("ma_npl"))
        if prepare_row.get("quantity") is not None:
            try:
                qty = float(prepare_row.get("quantity"))
            except (TypeError, ValueError):
                pass

    return {
        "line_no": line_no,
        "material_code": material,
        "product_code": product,
        "dg_case": dg,
        "color": color,
        "logo": logo,
        "quantity": qty,
        "detail": "",
        "plan_entry_id": int(plan["id"]),
        "prepare_item_id": int(prepare_row["id"]) if prepare_row and prepare_row.get("id") else None,
        "is_custom": False,
    }


def build_lines_from_plans(
    db: HubDatabase,
    plan_ids: list[int],
    *,
    ol_df: pd.DataFrame | None,
    bom_df: pd.DataFrame | None,
) -> tuple[list[dict[str, Any]], str]:
    """Mỗi plan phải đã Prepare — một dòng phiếu / dòng prepare."""
    plans: list[dict] = []
    for pid in plan_ids:
        conn = db._connect()
        import sqlite3

        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM planning_entries WHERE id = ? AND is_deleted = 0",
            (pid,),
        ).fetchone()
        conn.close()
        if row:
            plans.append(dict(row))

    if not plans:
        raise ValueError("Không có plan hợp lệ.")

    suppliers = {normalize_text(p.get("supplier")) for p in plans if normalize_text(p.get("supplier"))}
    if len(suppliers) != 1:
        raise ValueError("Tất cả plan trong phiếu phải cùng một Supplier.")

    on_pending = supplier_db.plan_ids_on_pending_slips(db)
    supplier = suppliers.pop()
    lines: list[dict] = []
    n = 1
    for plan in plans:
        if effective_check_status(plan) == "confirmed":
            raise ValueError(f"Plan {plan.get('dg_case')} đã lưu — không đưa vào phiếu mới.")
        pid = int(plan["id"])
        if pid in on_pending:
            raise ValueError(f"Plan {plan.get('dg_case')} đang nằm trong phiếu pending khác.")
        if effective_prepare_status(plan) != "prepared":
            raise ValueError(
                f"Plan {plan.get('dg_case')} chưa Prepare.\n"
                "Vào Planning → chọn ngày → Prepare trước khi tạo phiếu."
            )
        prepared = db.list_planning_prepare_items(pid)
        if not prepared:
            label_rows = list_label_candidates(bom_df, str(plan.get("dg_case", "")))
            if label_rows:
                raise ValueError(
                    f"Plan {plan.get('dg_case')} chưa Prepare dù có nhãn trong bảng kê.\n"
                    "Mở Prepare và chọn dòng nhãn trước."
                )
            raise ValueError(
                f"Plan {plan.get('dg_case')} không có dòng nhãn — kiểm tra bảng kê hoặc bỏ khỏi queue."
            )
        for pr in prepared:
            lines.append(
                build_line_from_plan(
                    db,
                    plan,
                    ol_df=ol_df,
                    bom_df=bom_df,
                    line_no=n,
                    prepare_row=pr,
                )
            )
            n += 1

    lines = apply_detail_autofill_lines(lines, db=db, ol_df=ol_df, bom_df=bom_df)
    return lines, supplier


def default_export_filename(slip: dict) -> str:
    code = normalize_text(slip.get("slip_code")) or f"PX-{slip.get('id')}"
    sup = normalize_text(slip.get("supplier")) or "supplier"
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in sup)[:40]
    created = normalize_text(slip.get("created_at"))[:10].replace("-", "")
    return f"{code}_{safe}_{created}.xlsx"

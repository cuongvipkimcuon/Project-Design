"""Quản lý tồn NPL — Pictogram (pcs) & Plastic Label (roll = pcs/100)."""

from __future__ import annotations

import json
import re
import sqlite3
import unicodedata
from datetime import datetime
from typing import Any

from core.db.dialect import now_iso
from core.permissions import can_manage_npl_types, normalize_role
from core.prepare_service import fold_text
from core.utils import normalize_text

MODULE_PICTOGRAM = "pictogram"
MODULE_PLASTIC_LABEL = "plastic_label"

DEFAULT_PICTOGRAM_PREFIX = "720.176.USA"
DEFAULT_PICTOGRAM_CODES: tuple[str, ...] = (
    f"{DEFAULT_PICTOGRAM_PREFIX}.S",
    f"{DEFAULT_PICTOGRAM_PREFIX}.M",
    f"{DEFAULT_PICTOGRAM_PREFIX}.L",
)
LEGACY_PICTOGRAM_CODES: dict[str, str] = {
    "S": DEFAULT_PICTOGRAM_CODES[0],
    "M": DEFAULT_PICTOGRAM_CODES[1],
    "L": DEFAULT_PICTOGRAM_CODES[2],
}

TXN_RECEIPT = "receipt"
TXN_SLIP_CHECK = "slip_check"
TXN_SLIP_UNCHECK = "slip_uncheck"
TXN_LOSS = "loss"
TXN_COMPENSATION = "compensation"

TXN_LABELS = {
    TXN_RECEIPT: "Nhập kho",
    TXN_SLIP_CHECK: "Phiếu check",
    TXN_SLIP_UNCHECK: "Gỡ check phiếu",
    TXN_LOSS: "Hư hao",
    TXN_COMPENSATION: "Bù đắp",
}

DEFAULT_STOCK_TYPES: list[dict[str, Any]] = [
    {
        "module": MODULE_PICTOGRAM,
        "code": DEFAULT_PICTOGRAM_CODES[0],
        "name": "Pictogram S",
        "unit_label": "pcs",
        "divisor": 1.0,
        "sort_order": 1,
    },
    {
        "module": MODULE_PICTOGRAM,
        "code": DEFAULT_PICTOGRAM_CODES[1],
        "name": "Pictogram M",
        "unit_label": "pcs",
        "divisor": 1.0,
        "sort_order": 2,
    },
    {
        "module": MODULE_PICTOGRAM,
        "code": DEFAULT_PICTOGRAM_CODES[2],
        "name": "Pictogram L",
        "unit_label": "pcs",
        "divisor": 1.0,
        "sort_order": 3,
    },
    {
        "module": MODULE_PLASTIC_LABEL,
        "code": "blue",
        "name": "Blue Label",
        "unit_label": "roll",
        "divisor": 100.0,
        "sort_order": 1,
    },
    {
        "module": MODULE_PLASTIC_LABEL,
        "code": "white",
        "name": "White Label",
        "unit_label": "roll",
        "divisor": 100.0,
        "sort_order": 2,
    },
]


def format_qty(value: float) -> str:
    if value == int(value):
        return str(int(value))
    text = f"{value:.4f}".rstrip("0").rstrip(".")
    return text or "0"


INPUT_UNIT_PCS = "pcs"
INPUT_UNIT_ROLL = "roll"


def input_to_pcs(stock_type: dict[str, Any], qty: float, input_unit: str) -> float:
    if qty <= 0:
        raise ValueError("Số lượng phải > 0.")
    unit = normalize_text(input_unit) or INPUT_UNIT_PCS
    storage = normalize_text(stock_type.get("unit_label")) or INPUT_UNIT_PCS
    divisor = float(stock_type.get("divisor") or 1.0)
    if divisor <= 0:
        divisor = 1.0
    if unit == INPUT_UNIT_ROLL:
        if storage != "roll":
            raise ValueError("Loại NPL này không nhập theo roll.")
        return qty * divisor
    if unit != INPUT_UNIT_PCS:
        raise ValueError("Đơn vị nhập không hợp lệ.")
    return qty


def balance_display_parts(stock_type: dict[str, Any]) -> tuple[str, str]:
    bal = float(stock_type.get("balance") or 0)
    unit = normalize_text(stock_type.get("unit_label")) or INPUT_UNIT_PCS
    if unit == "roll":
        divisor = float(stock_type.get("divisor") or 100)
        pcs_equiv = bal * divisor
        return f"{format_qty(bal)} roll", f"~{format_qty(pcs_equiv)} pcs"
    return f"{format_qty(bal)} pcs", ""


def _material_matches_type_code(material_code: str, type_code: str, module: str) -> bool:
    mat = normalize_text(material_code).replace(" ", "")
    code = normalize_text(type_code).replace(" ", "")
    if not mat or not code:
        return False
    mat_u, code_u = mat.upper(), code.upper()
    if module == MODULE_PICTOGRAM:
        if "." in code_u:
            return mat_u == code_u or mat_u.startswith(f"{code_u}.")
        parts = [p for p in mat_u.split(".") if p]
        if parts and parts[-1] == code_u:
            return True
        if mat_u.endswith(code_u):
            return True
        return False
    mat_f = mat_u.replace(".", "")
    code_f = code_u.replace(".", "")
    return mat_f.startswith(code_f) or code_f in mat_f


def classify_pictogram_material(
    material_code: str,
    types: list[dict[str, Any]] | None = None,
    *,
    db=None,
) -> str | None:
    """Map mã NPL bảng kê → mã loại Pictogram đang theo dõi (cùng rule trừ tồn phiếu)."""
    mat = normalize_text(material_code).replace(" ", "")
    if not mat.upper().startswith("720"):
        return None
    if types is None:
        if db is None:
            return None
        types = NplStockService(db).list_types(MODULE_PICTOGRAM)
    if not types:
        return None
    return _classify_from_custom_types(mat, types, MODULE_PICTOGRAM)


def _classify_from_custom_types(
    material_code: str,
    types: list[dict[str, Any]],
    module: str,
) -> str | None:
    mat = normalize_text(material_code).replace(" ", "")
    if not mat:
        return None
    for item in sorted(types, key=lambda x: -len(normalize_text(x.get("code")))):
        code = normalize_text(item.get("code"))
        if code and _material_matches_type_code(mat, code, module):
            return code
    return None


def _pictogram_size_from_material(material_code: str) -> str:
    parts = [p for p in normalize_text(material_code).replace(" ", "").split(".") if p]
    if not parts:
        return ""
    suffix = parts[-1].upper()
    return suffix if len(suffix) == 1 else ""


def _plastic_label_from_material(material_code: str) -> str | None:
    """705.204… → blue, 705.800… → white (nhãn nhựa)."""
    mat = normalize_text(material_code).replace(" ", "")
    if mat.startswith("705.204") or mat.startswith("705204"):
        return "blue"
    if mat.startswith("705.800") or mat.startswith("705800"):
        return "white"
    return None


def classify_slip_line(
    line: dict[str, Any],
    *,
    ten_npl: str = "",
    mo_ta: str = "",
    db=None,
) -> tuple[str, str] | None:
    """Map dòng phiếu → (module, type_code)."""
    mat = normalize_text(line.get("material_code")).replace(" ", "")
    detail = normalize_text(line.get("detail"))
    blob = fold_text(" ".join([mat, detail, ten_npl, mo_ta, normalize_text(line.get("color"))]))

    if mat.startswith("720"):
        if db is not None:
            hit = classify_pictogram_material(mat, db=db)
            if hit:
                return MODULE_PICTOGRAM, hit
        size = _pictogram_size_from_material(mat)
        if size in LEGACY_PICTOGRAM_CODES:
            return MODULE_PICTOGRAM, LEGACY_PICTOGRAM_CODES[size]

    label_code = _plastic_label_from_material(mat)
    if label_code:
        return MODULE_PLASTIC_LABEL, label_code

    if db is not None:
        svc = NplStockService(db)
        for module in (MODULE_PLASTIC_LABEL, MODULE_PICTOGRAM):
            custom = _classify_from_custom_types(mat, svc.list_types(module), module)
            if custom:
                return module, custom

    if "blue label" in blob or "nhan xanh" in blob or "label xanh" in blob or re.search(r"\bblue\b", blob):
        return MODULE_PLASTIC_LABEL, "blue"
    if "white label" in blob or "nhan trang" in blob or "label trang" in blob or re.search(r"\bwhite\b", blob):
        return MODULE_PLASTIC_LABEL, "white"

    if mat.startswith("704"):
        if "blue" in blob or "xanh" in blob:
            return MODULE_PLASTIC_LABEL, "blue"
        if "white" in blob or "trang" in blob:
            return MODULE_PLASTIC_LABEL, "white"
    return None


def suggest_stock_mapping(
    *,
    ma_npl: str,
    ten_npl: str = "",
    mo_ta: str = "",
    db=None,
) -> tuple[str, str] | None:
    """Gợi ý map tồn từ mã NPL / tên NPL (không gồm override prepare)."""
    return classify_slip_line(
        {"material_code": ma_npl},
        ten_npl=ten_npl,
        mo_ta=mo_ta,
        db=db,
    )


def suggest_stock_mapping_label(db, *, ma_npl: str, ten_npl: str = "", mo_ta: str = "") -> str:
    mapped = suggest_stock_mapping(ma_npl=ma_npl, ten_npl=ten_npl, mo_ta=mo_ta, db=db)
    if not mapped:
        return "—"
    module, code = mapped
    stock_type = NplStockService(db).find_type(module, code)
    if stock_type:
        return normalize_text(stock_type.get("name")) or code
    return f"{module}/{code}"


class NplStockService:
    def __init__(self, db) -> None:
        self.db = db

    def _oid(self) -> str:
        from core.team_ops_sync import team_ops_owner_id

        return team_ops_owner_id(self.db)

    def _ops_changed(self, *, actor: str = "") -> None:
        from core.team_ops_sync import notify_team_ops_changed

        notify_team_ops_changed(self.db, actor_name=actor)

    def ensure_defaults(self, conn: sqlite3.Connection | None = None) -> None:
        own = conn is None
        if own:
            conn = self.db._connect()
        oid = self._oid()
        self._migrate_legacy_pictogram_codes(conn, oid)
        for item in DEFAULT_STOCK_TYPES:
            row = conn.execute(
                """
                SELECT id FROM npl_stock_types
                WHERE owner_id = ? AND module = ? AND code = ?
                """,
                (oid, item["module"], item["code"]),
            ).fetchone()
            if row:
                continue
            conn.execute(
                """
                INSERT INTO npl_stock_types(
                    owner_id, module, code, name, unit_label, divisor, sort_order, is_active, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)
                """,
                (
                    oid,
                    item["module"],
                    item["code"],
                    item["name"],
                    item["unit_label"],
                    float(item["divisor"]),
                    int(item["sort_order"]),
                    now_iso(),
                ),
            )
        if own:
            conn.commit()
            conn.close()

    def _migrate_legacy_pictogram_codes(self, conn: sqlite3.Connection, oid: str) -> None:
        """Đổi mã mặc định cũ S/M/L → 720.176.USA.S|M|L (giữ tồn & lịch sử)."""
        for old_code, new_code in LEGACY_PICTOGRAM_CODES.items():
            old = conn.execute(
                """
                SELECT id, name FROM npl_stock_types
                WHERE owner_id = ? AND module = ? AND code = ?
                """,
                (oid, MODULE_PICTOGRAM, old_code),
            ).fetchone()
            if not old:
                continue
            exists = conn.execute(
                """
                SELECT id FROM npl_stock_types
                WHERE owner_id = ? AND module = ? AND code = ?
                """,
                (oid, MODULE_PICTOGRAM, new_code),
            ).fetchone()
            if exists:
                continue
            name = normalize_text(old[1]) or f"Pictogram {new_code.split('.')[-1]}"
            conn.execute(
                "UPDATE npl_stock_types SET code = ?, name = ? WHERE id = ?",
                (new_code, name, int(old[0])),
            )

    def list_types(self, module: str, *, active_only: bool = True) -> list[dict[str, Any]]:
        self.ensure_defaults()
        conn = self.db._connect()
        conn.row_factory = sqlite3.Row
        sql = """
            SELECT t.*, COALESCE(b.balance, 0) AS balance
            FROM npl_stock_types t
            LEFT JOIN npl_stock_balances b
                ON b.stock_type_id = t.id AND b.owner_id = t.owner_id
            WHERE t.owner_id = ? AND t.module = ?
        """
        params: list[Any] = [self._oid(), module]
        if active_only:
            sql += " AND t.is_active = 1"
        sql += " ORDER BY t.sort_order ASC, t.name ASC"
        rows = conn.execute(sql, params).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_type(self, type_id: int) -> dict[str, Any] | None:
        conn = self.db._connect()
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """
            SELECT t.*, COALESCE(b.balance, 0) AS balance
            FROM npl_stock_types t
            LEFT JOIN npl_stock_balances b
                ON b.stock_type_id = t.id AND b.owner_id = t.owner_id
            WHERE t.id = ? AND t.owner_id = ?
            """,
            (type_id, self._oid()),
        ).fetchone()
        conn.close()
        return dict(row) if row else None

    def find_type(self, module: str, code: str) -> dict[str, Any] | None:
        conn = self.db._connect()
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """
            SELECT t.*, COALESCE(b.balance, 0) AS balance
            FROM npl_stock_types t
            LEFT JOIN npl_stock_balances b
                ON b.stock_type_id = t.id AND b.owner_id = t.owner_id
            WHERE t.owner_id = ? AND t.module = ? AND t.code = ? AND t.is_active = 1
            """,
            (self._oid(), module, code),
        ).fetchone()
        conn.close()
        return dict(row) if row else None

    def _find_type_conn(
        self,
        conn: sqlite3.Connection,
        module: str,
        code: str,
    ) -> dict[str, Any] | None:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """
            SELECT t.*, COALESCE(b.balance, 0) AS balance
            FROM npl_stock_types t
            LEFT JOIN npl_stock_balances b
                ON b.stock_type_id = t.id AND b.owner_id = t.owner_id
            WHERE t.owner_id = ? AND t.module = ? AND t.code = ? AND t.is_active = 1
            """,
            (self._oid(), module, code),
        ).fetchone()
        return dict(row) if row else None

    def _find_type_by_id_conn(self, conn: sqlite3.Connection, type_id: int) -> dict[str, Any] | None:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """
            SELECT t.*, COALESCE(b.balance, 0) AS balance
            FROM npl_stock_types t
            LEFT JOIN npl_stock_balances b
                ON b.stock_type_id = t.id AND b.owner_id = t.owner_id
            WHERE t.id = ? AND t.owner_id = ? AND t.is_active = 1
            """,
            (type_id, self._oid()),
        ).fetchone()
        return dict(row) if row else None

    def list_stock_type_choices(self) -> list[dict[str, Any]]:
        self.ensure_defaults()
        out: list[dict[str, Any]] = []
        for module in (MODULE_PICTOGRAM, MODULE_PLASTIC_LABEL):
            for item in self.list_types(module):
                out.append(dict(item))
        return out

    def module_summary(self, module: str) -> dict[str, Any]:
        types = self.list_types(module)
        total_balance = 0.0
        total_pcs_equiv = 0.0
        for item in types:
            bal = float(item.get("balance") or 0)
            unit = normalize_text(item.get("unit_label")) or INPUT_UNIT_PCS
            total_balance += bal
            if unit == "roll":
                total_pcs_equiv += bal * float(item.get("divisor") or 100)
            else:
                total_pcs_equiv += bal
        ledger_count = len(self.list_ledger(module, limit=500))
        return {
            "type_count": len(types),
            "total_balance": total_balance,
            "total_pcs_equiv": total_pcs_equiv,
            "ledger_count": ledger_count,
            "unit_label": "roll" if module == MODULE_PLASTIC_LABEL else INPUT_UNIT_PCS,
        }

    def resolve_slip_line_stock_type(
        self,
        conn: sqlite3.Connection,
        line: dict[str, Any],
    ) -> tuple[dict[str, Any] | None, str]:
        """Ưu tiên map thủ công trên prepare; không có thì map tự động."""
        ten_npl, mo_ta = "", ""
        prepare_item_id = line.get("prepare_item_id")
        if prepare_item_id:
            row = conn.execute(
                """
                SELECT npl_stock_type_id, ten_npl, mo_ta
                FROM planning_prepare_items
                WHERE id = ?
                """,
                (int(prepare_item_id),),
            ).fetchone()
            if row:
                ten_npl = normalize_text(row[1])
                mo_ta = normalize_text(row[2])
                manual_id = row[0]
                if manual_id:
                    stock_type = self._find_type_by_id_conn(conn, int(manual_id))
                    if stock_type:
                        return stock_type, "manual"

        mapped = classify_slip_line(line, ten_npl=ten_npl, mo_ta=mo_ta, db=self.db)
        if not mapped:
            return None, ""
        module, code = mapped
        stock_type = self._find_type_conn(conn, module, code)
        if stock_type:
            return stock_type, "auto"
        return None, ""

    def _require_admin_types(self, actor_role: str | None) -> None:
        role = normalize_role(actor_role)
        if not can_manage_npl_types(role):
            raise PermissionError("Chỉ admin được thêm / sửa / xóa loại NPL theo dõi.")

    def add_stock_type(self, *, module: str, code: str, name: str, actor_role: str | None = None) -> int:
        self._require_admin_types(actor_role)
        raw = normalize_text(code).replace(" ", "")
        if not raw:
            raise ValueError("Mã khớp NPL không được trống.")
        if module == MODULE_PICTOGRAM:
            code_norm = raw.upper()
            unit_label, divisor = INPUT_UNIT_PCS, 1.0
            default_name = f"Pictogram {code_norm}"
        elif module == MODULE_PLASTIC_LABEL:
            code_norm = raw.lower()
            unit_label, divisor = "roll", 100.0
            default_name = f"Label {code_norm}"
        else:
            raise ValueError("Module không hợp lệ.")
        display = normalize_text(name) or default_name
        self.ensure_defaults()
        conn = self.db._connect()
        exists = conn.execute(
            """
            SELECT 1 FROM npl_stock_types
            WHERE owner_id = ? AND module = ? AND code = ?
            """,
            (self._oid(), module, code_norm),
        ).fetchone()
        if exists:
            conn.close()
            raise ValueError(f"Loại «{code_norm}» đã tồn tại.")
        cur = conn.execute(
            """
            INSERT INTO npl_stock_types(
                owner_id, module, code, name, unit_label, divisor, sort_order, is_active, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, (SELECT COALESCE(MAX(sort_order), 0) + 1 FROM npl_stock_types WHERE owner_id = ? AND module = ?), 1, ?)
            """,
            (
                self._oid(),
                module,
                code_norm,
                display,
                unit_label,
                divisor,
                self._oid(),
                module,
                now_iso(),
            ),
        )
        type_id = int(cur.lastrowid)
        conn.commit()
        conn.close()
        self._ops_changed()
        return type_id

    def update_stock_type(
        self, type_id: int, *, code: str, name: str, actor_role: str | None = None
    ) -> None:
        self._require_admin_types(actor_role)
        stock_type = self.get_type(int(type_id))
        if not stock_type:
            raise ValueError("Loại NPL không tồn tại.")
        module = normalize_text(stock_type.get("module"))
        raw = normalize_text(code).replace(" ", "")
        if not raw:
            raise ValueError("Mã khớp NPL không được trống.")
        if module == MODULE_PICTOGRAM:
            code_norm = raw.upper()
            default_name = f"Pictogram {code_norm}"
        elif module == MODULE_PLASTIC_LABEL:
            code_norm = raw.lower()
            default_name = f"Label {code_norm}"
        else:
            raise ValueError("Module không hợp lệ.")
        display = normalize_text(name) or default_name
        conn = self.db._connect()
        dup = conn.execute(
            """
            SELECT id FROM npl_stock_types
            WHERE owner_id = ? AND module = ? AND code = ? AND id != ? AND is_active = 1
            """,
            (self._oid(), module, code_norm, int(type_id)),
        ).fetchone()
        if dup:
            conn.close()
            raise ValueError(f"Loại «{code_norm}» đã tồn tại.")
        conn.execute(
            """
            UPDATE npl_stock_types SET code = ?, name = ? WHERE id = ? AND owner_id = ?
            """,
            (code_norm, display, int(type_id), self._oid()),
        )
        conn.commit()
        conn.close()
        self._ops_changed()

    def delete_stock_type(self, type_id: int, *, actor_role: str | None = None) -> None:
        self._require_admin_types(actor_role)
        stock_type = self.get_type(int(type_id))
        if not stock_type:
            raise ValueError("Loại NPL không tồn tại.")
        balance = float(stock_type.get("balance") or 0)
        if balance > 1e-9:
            unit = normalize_text(stock_type.get("unit_label")) or INPUT_UNIT_PCS
            raise ValueError(
                f"Loại «{stock_type.get('name')}» còn tồn {format_qty(balance)} {unit} — "
                "xuất hết hoặc chuyển tồn trước khi xóa."
            )
        conn = self.db._connect()
        conn.execute(
            """
            UPDATE npl_stock_types SET is_active = 0 WHERE id = ? AND owner_id = ?
            """,
            (int(type_id), self._oid()),
        )
        conn.commit()
        conn.close()
        self._ops_changed()

    def add_pictogram_type(self, *, code: str, name: str, actor_role: str | None = None) -> int:
        return self.add_stock_type(
            module=MODULE_PICTOGRAM, code=code, name=name, actor_role=actor_role
        )

    def pcs_to_balance_delta(self, stock_type: dict[str, Any], pcs: float, *, sign: int) -> float:
        divisor = float(stock_type.get("divisor") or 1.0)
        if divisor <= 0:
            divisor = 1.0
        unit = normalize_text(stock_type.get("unit_label")) or "pcs"
        if unit == "roll":
            return sign * (pcs / divisor)
        return sign * pcs

    def _next_batch_code(self, conn: sqlite3.Connection, stock_type: dict[str, Any]) -> str:
        oid = self._oid()
        type_id = int(stock_type["id"])
        code = normalize_text(stock_type.get("code")).upper() or "X"
        code = re.sub(r"[^A-Z0-9]", "", code)[:8] or "X"
        yymm = datetime.now().strftime("%y%m")
        prefix = f"NH-{code}-{yymm}-"
        row = conn.execute(
            """
            SELECT COUNT(*) FROM npl_stock_batches
            WHERE owner_id = ? AND stock_type_id = ? AND batch_code LIKE ?
            """,
            (oid, type_id, f"{prefix}%"),
        ).fetchone()
        seq = int(row[0]) + 1 if row else 1
        return f"{prefix}{seq:03d}"

    def _ensure_legacy_batches(self, conn: sqlite3.Connection) -> None:
        """Tồn cũ chưa có lô → gom thành 1 batch LEGACY."""
        oid = self._oid()
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT t.id, t.code, t.unit_label, t.divisor, COALESCE(b.balance, 0) AS balance
            FROM npl_stock_types t
            LEFT JOIN npl_stock_balances b
                ON b.stock_type_id = t.id AND b.owner_id = t.owner_id
            WHERE t.owner_id = ? AND t.is_active = 1
            """,
            (oid,),
        ).fetchall()
        ts = now_iso()
        for row in rows:
            bal = float(row["balance"] or 0)
            if bal <= 0:
                continue
            type_id = int(row["id"])
            cnt = conn.execute(
                "SELECT COUNT(*) FROM npl_stock_batches WHERE owner_id = ? AND stock_type_id = ?",
                (oid, type_id),
            ).fetchone()[0]
            if int(cnt) > 0:
                continue
            code = normalize_text(row["code"]).upper() or "X"
            batch_code = f"LEGACY-{code}-001"
            unit = normalize_text(row["unit_label"]) or INPUT_UNIT_PCS
            divisor = float(row["divisor"] or 1.0)
            pcs = bal * divisor if unit == "roll" else bal
            conn.execute(
                """
                INSERT INTO npl_stock_batches(
                    owner_id, stock_type_id, batch_code, balance, qty_pcs_initial,
                    receipt_ledger_id, note, actor, created_at
                )
                VALUES (?, ?, ?, ?, ?, NULL, 'Tồn trước khi bật quản lý lô', 'system', ?)
                """,
                (oid, type_id, batch_code, bal, pcs, ts),
            )

    def _batch_balance_total(self, conn: sqlite3.Connection, stock_type_id: int) -> float:
        oid = self._oid()
        row = conn.execute(
            """
            SELECT COALESCE(SUM(balance), 0) FROM npl_stock_batches
            WHERE owner_id = ? AND stock_type_id = ? AND balance > 0
            """,
            (oid, stock_type_id),
        ).fetchone()
        return float(row[0]) if row else 0.0

    def _create_batch(
        self,
        conn: sqlite3.Connection,
        *,
        stock_type: dict[str, Any],
        balance_qty: float,
        qty_pcs: float,
        batch_code: str,
        actor: str,
        note: str = "",
        receipt_ledger_id: int | None = None,
    ) -> dict[str, Any]:
        oid = self._oid()
        type_id = int(stock_type["id"])
        cur = conn.execute(
            """
            INSERT INTO npl_stock_batches(
                owner_id, stock_type_id, batch_code, balance, qty_pcs_initial,
                receipt_ledger_id, note, actor, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                oid,
                type_id,
                batch_code,
                balance_qty,
                qty_pcs,
                receipt_ledger_id,
                normalize_text(note),
                normalize_text(actor),
                now_iso(),
            ),
        )
        return {
            "batch_id": int(cur.lastrowid),
            "batch_code": batch_code,
            "balance": balance_qty,
        }

    def _fifo_consume(
        self,
        conn: sqlite3.Connection,
        *,
        stock_type_id: int,
        qty_balance: float,
    ) -> list[dict[str, Any]]:
        """Trừ lô theo FIFO — qty_balance theo đơn vị lưu (roll/pcs)."""
        if qty_balance <= 0:
            return []
        oid = self._oid()
        self._ensure_legacy_batches(conn)
        rows = conn.execute(
            """
            SELECT id, batch_code, balance FROM npl_stock_batches
            WHERE owner_id = ? AND stock_type_id = ? AND balance > 0
            ORDER BY created_at ASC, id ASC
            """,
            (oid, stock_type_id),
        ).fetchall()
        remaining = qty_balance
        moves: list[dict[str, Any]] = []
        for batch_id, batch_code, bal in rows:
            if remaining <= 1e-9:
                break
            available = float(bal)
            take = min(available, remaining)
            new_bal = available - take
            conn.execute(
                "UPDATE npl_stock_batches SET balance = ? WHERE id = ?",
                (new_bal, int(batch_id)),
            )
            moves.append(
                {
                    "batch_id": int(batch_id),
                    "batch_code": normalize_text(batch_code),
                    "qty": take,
                }
            )
            remaining -= take
        return moves

    def _restore_batch_moves(self, conn: sqlite3.Connection, moves: list[dict[str, Any]]) -> None:
        for move in moves:
            batch_id = int(move.get("batch_id") or 0)
            qty = float(move.get("qty") or 0)
            if batch_id <= 0 or qty <= 0:
                continue
            conn.execute(
                "UPDATE npl_stock_batches SET balance = balance + ? WHERE id = ?",
                (qty, batch_id),
            )

    def list_batches(self, module: str, *, stock_type_id: int | None = None) -> list[dict[str, Any]]:
        self.ensure_defaults()
        conn = self.db._connect()
        conn.row_factory = sqlite3.Row
        try:
            self._ensure_legacy_batches(conn)
            conn.commit()
            sql = """
                SELECT b.*, t.code AS type_code, t.name AS type_name, t.unit_label, t.module, t.divisor
                FROM npl_stock_batches b
                JOIN npl_stock_types t ON t.id = b.stock_type_id
                WHERE b.owner_id = ? AND t.module = ?
            """
            params: list[Any] = [self._oid(), module]
            if stock_type_id:
                sql += " AND b.stock_type_id = ?"
                params.append(stock_type_id)
            sql += " ORDER BY b.created_at ASC, b.id ASC"
            rows = conn.execute(sql, params).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def _apply_balance(
        self,
        conn: sqlite3.Connection,
        *,
        stock_type_id: int,
        qty_pcs: float,
        qty_delta: float,
        txn_type: str,
        actor: str,
        note: str = "",
        slip_id: int | None = None,
        slip_line_id: int | None = None,
        ref_txn_id: int | None = None,
        meta: dict | None = None,
    ) -> dict[str, Any]:
        oid = self._oid()
        row = conn.execute(
            "SELECT balance FROM npl_stock_balances WHERE owner_id = ? AND stock_type_id = ?",
            (oid, stock_type_id),
        ).fetchone()
        current = float(row[0]) if row else 0.0
        new_balance = current + qty_delta
        if row:
            conn.execute(
                "UPDATE npl_stock_balances SET balance = ? WHERE owner_id = ? AND stock_type_id = ?",
                (new_balance, oid, stock_type_id),
            )
        else:
            conn.execute(
                """
                INSERT INTO npl_stock_balances(owner_id, stock_type_id, balance)
                VALUES (?, ?, ?)
                """,
                (oid, stock_type_id, new_balance),
            )
        cur = conn.execute(
            """
            INSERT INTO npl_stock_ledger(
                owner_id, stock_type_id, txn_type, qty_pcs, qty_delta, balance_after,
                slip_id, slip_line_id, ref_txn_id, note, actor, meta_json, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                oid,
                stock_type_id,
                txn_type,
                qty_pcs,
                qty_delta,
                new_balance,
                slip_id,
                slip_line_id,
                ref_txn_id,
                normalize_text(note),
                normalize_text(actor),
                json.dumps(meta or {}, ensure_ascii=False),
                now_iso(),
            ),
        )
        return {"ledger_id": int(cur.lastrowid), "balance_after": new_balance}

    def record_manual(
        self,
        *,
        stock_type_id: int,
        txn_type: str,
        qty: float,
        input_unit: str = INPUT_UNIT_PCS,
        actor: str,
        note: str = "",
    ) -> dict[str, Any]:
        if txn_type not in (TXN_RECEIPT, TXN_LOSS, TXN_COMPENSATION):
            raise ValueError("Loại giao dịch không hợp lệ.")
        stock_type = self.get_type(stock_type_id)
        if not stock_type:
            raise ValueError("Không tìm thấy loại NPL.")
        qty_pcs = input_to_pcs(stock_type, qty, input_unit)
        sign = 1 if txn_type in (TXN_RECEIPT, TXN_COMPENSATION) else -1
        qty_delta = self.pcs_to_balance_delta(stock_type, qty_pcs, sign=sign)
        meta: dict[str, Any] = {"input_unit": input_unit, "input_qty": qty}
        conn = self.db._connect()
        try:
            self._ensure_legacy_batches(conn)
            batch_info: dict[str, Any] | None = None
            if sign < 0:
                consume_qty = abs(qty_delta)
                moves = self._fifo_consume(
                    conn, stock_type_id=stock_type_id, qty_balance=consume_qty
                )
                meta["batch_moves"] = moves
                if moves:
                    meta["batch_code"] = ", ".join(m["batch_code"] for m in moves)
            out = self._apply_balance(
                conn,
                stock_type_id=stock_type_id,
                qty_pcs=qty_pcs,
                qty_delta=qty_delta,
                txn_type=txn_type,
                actor=actor,
                note=note,
                meta=meta,
            )
            if sign > 0:
                batch_code = self._next_batch_code(conn, stock_type)
                batch_info = self._create_batch(
                    conn,
                    stock_type=stock_type,
                    balance_qty=qty_delta,
                    qty_pcs=qty_pcs,
                    batch_code=batch_code,
                    actor=actor,
                    note=note,
                    receipt_ledger_id=int(out["ledger_id"]),
                )
                meta["batch_code"] = batch_code
                meta["batch_id"] = batch_info["batch_id"]
                conn.execute(
                    "UPDATE npl_stock_ledger SET meta_json = ? WHERE id = ?",
                    (json.dumps(meta, ensure_ascii=False), int(out["ledger_id"])),
                )
                out["batch_code"] = batch_code
                out["batch_id"] = batch_info["batch_id"]
            conn.commit()
            self._ops_changed(actor=actor)
            return out
        finally:
            conn.close()

    def list_ledger(self, module: str, *, limit: int = 800) -> list[dict[str, Any]]:
        conn = self.db._connect()
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT l.*, t.code AS type_code, t.name AS type_name, t.unit_label, t.module,
                   s.slip_code
            FROM npl_stock_ledger l
            JOIN npl_stock_types t ON t.id = l.stock_type_id
            LEFT JOIN supplier_slips s ON s.id = l.slip_id AND s.owner_id = l.owner_id
            WHERE l.owner_id = ? AND t.module = ?
            ORDER BY l.created_at DESC, l.id DESC
            LIMIT ?
            """,
            (self._oid(), module, max(1, limit)),
        ).fetchall()
        conn.close()
        out: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            try:
                item["meta"] = json.loads(item.pop("meta_json") or "{}")
            except json.JSONDecodeError:
                item["meta"] = {}
            out.append(item)
        return out

    def _prepare_meta(self, conn: sqlite3.Connection, prepare_item_id: int | None) -> tuple[str, str]:
        if not prepare_item_id:
            return "", ""
        row = conn.execute(
            "SELECT ten_npl, mo_ta FROM planning_prepare_items WHERE id = ?",
            (int(prepare_item_id),),
        ).fetchone()
        if not row:
            return "", ""
        return normalize_text(row[0]), normalize_text(row[1])

    def preview_slip_check(self, slip: dict[str, Any]) -> list[dict[str, Any]]:
        """Mô phỏng trừ tồn — trả về cảnh báo nếu balance_after < 0."""
        conn = self.db._connect()
        try:
            self.ensure_defaults(conn)
            self._ensure_legacy_batches(conn)
            warnings: list[dict[str, Any]] = []
            projected: dict[int, float] = {}
            oid = self._oid()
            for line in slip.get("lines") or []:
                stock_type, _map_source = self.resolve_slip_line_stock_type(conn, line)
                if not stock_type:
                    continue
                type_id = int(stock_type["id"])
                pcs = float(line.get("quantity") or 0)
                if pcs <= 0:
                    continue
                qty_delta = self.pcs_to_balance_delta(stock_type, pcs, sign=-1)
                if type_id not in projected:
                    batch_total = self._batch_balance_total(conn, type_id)
                    if batch_total > 0:
                        projected[type_id] = batch_total
                    else:
                        row = conn.execute(
                            "SELECT balance FROM npl_stock_balances WHERE owner_id = ? AND stock_type_id = ?",
                            (oid, type_id),
                        ).fetchone()
                        projected[type_id] = float(row[0]) if row else 0.0
                before = projected[type_id]
                after = before + qty_delta
                projected[type_id] = after
                if after < -1e-9:
                    warnings.append(
                        {
                            "type_name": normalize_text(stock_type.get("name")),
                            "type_code": normalize_text(stock_type.get("code")),
                            "unit_label": normalize_text(stock_type.get("unit_label")) or "pcs",
                            "before": before,
                            "delta": qty_delta,
                            "after": after,
                            "pcs": pcs,
                            "material_code": normalize_text(line.get("material_code")),
                        }
                    )
            return warnings
        finally:
            conn.close()

    def apply_slip_check(
        self,
        conn: sqlite3.Connection,
        slip: dict[str, Any],
        *,
        actor: str,
    ) -> list[dict[str, Any]]:
        self.ensure_defaults(conn)
        self._ensure_legacy_batches(conn)
        applied: list[dict[str, Any]] = []
        slip_id = int(slip["id"])
        for line in slip.get("lines") or []:
            line_id = int(line.get("id") or 0)
            stock_type, map_source = self.resolve_slip_line_stock_type(conn, line)
            if not stock_type:
                continue
            pcs = float(line.get("quantity") or 0)
            if pcs <= 0:
                continue
            qty_delta = self.pcs_to_balance_delta(stock_type, pcs, sign=-1)
            consume_qty = abs(qty_delta)
            moves = self._fifo_consume(
                conn, stock_type_id=int(stock_type["id"]), qty_balance=consume_qty
            )
            meta = {
                "material_code": normalize_text(line.get("material_code")),
                "dg_case": normalize_text(line.get("dg_case")),
                "slip_code": normalize_text(slip.get("slip_code")),
                "mapped_module": normalize_text(stock_type.get("module")),
                "mapped_code": normalize_text(stock_type.get("code")),
                "map_source": map_source,
                "batch_moves": moves,
            }
            if moves:
                meta["batch_code"] = ", ".join(m["batch_code"] for m in moves)
            out = self._apply_balance(
                conn,
                stock_type_id=int(stock_type["id"]),
                qty_pcs=pcs,
                qty_delta=qty_delta,
                txn_type=TXN_SLIP_CHECK,
                actor=actor,
                note=f"Phiếu {slip.get('slip_code', slip_id)} · {normalize_text(line.get('material_code'))}",
                slip_id=slip_id,
                slip_line_id=line_id or None,
                meta=meta,
            )
            applied.append(
                {
                    **out,
                    "type_code": normalize_text(stock_type.get("code")),
                    "module": normalize_text(stock_type.get("module")),
                    "qty_pcs": pcs,
                    "map_source": map_source,
                }
            )
        return applied

    def revert_slip_check(
        self,
        conn: sqlite3.Connection,
        slip_id: int,
        *,
        actor: str,
        note: str = "",
    ) -> list[dict[str, Any]]:
        oid = self._oid()
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT id, stock_type_id, qty_pcs, qty_delta, slip_line_id, meta_json
            FROM npl_stock_ledger
            WHERE owner_id = ? AND slip_id = ? AND txn_type = ?
            ORDER BY id ASC
            """,
            (oid, slip_id, TXN_SLIP_CHECK),
        ).fetchall()
        reverted: list[dict[str, Any]] = []
        for row in rows:
            try:
                meta = json.loads(row["meta_json"] or "{}")
            except json.JSONDecodeError:
                meta = {}
            moves = meta.get("batch_moves") or []
            if moves:
                self._restore_batch_moves(conn, moves)
            out = self._apply_balance(
                conn,
                stock_type_id=int(row["stock_type_id"]),
                qty_pcs=float(row["qty_pcs"]),
                qty_delta=-float(row["qty_delta"]),
                txn_type=TXN_SLIP_UNCHECK,
                actor=actor,
                note=note or f"Gỡ check phiếu #{slip_id}",
                slip_id=slip_id,
                slip_line_id=int(row["slip_line_id"]) if row["slip_line_id"] else None,
                ref_txn_id=int(row["id"]),
            )
            reverted.append(out)
        return reverted

"""Phân quyền theo role: admin | design | sales."""

from __future__ import annotations

ROLES = ("admin", "design", "sales")
DEFAULT_ROLE = "design"

# Module keys
MOD_SETUP_ACCOUNT = "setup_account"
MOD_SETUP_PERMISSIONS = "setup_permissions"
MOD_SALES = "sales"
MOD_DESIGN_PLANNING = "design_planning"
MOD_DESIGN_PLASTIC = "design_plastic"
MOD_DESIGN_PICTOGRAM = "design_pictogram"
MOD_DESIGN_SUPPLIER = "design_supplier"

_DESIGN_MODULES = frozenset(
    {
        MOD_DESIGN_PLANNING,
        MOD_DESIGN_PLASTIC,
        MOD_DESIGN_PICTOGRAM,
        MOD_DESIGN_SUPPLIER,
    }
)


def normalize_role(role: str | None) -> str:
    r = (role or "").strip().lower()
    return r if r in ROLES else DEFAULT_ROLE


def role_label(role: str) -> str:
    labels = {"admin": "Admin", "design": "Design", "sales": "Sales"}
    return labels.get(normalize_role(role), role)


def can_access(role: str, module: str) -> bool:
    """Tab/module hiển thị theo role."""
    r = normalize_role(role)
    if module == MOD_SETUP_PERMISSIONS:
        return r == "admin"
    if module in _DESIGN_MODULES:
        return r in ("admin", "design")
    if module == MOD_SALES:
        return r in ("admin", "sales")
    if module == MOD_SETUP_ACCOUNT:
        return r in ("admin", "design", "sales")
    return True


def visible_nav_pages(role: str) -> list[tuple[str, str]]:
    """Sidebar: (key, label)."""
    r = normalize_role(role)
    pages: list[tuple[str, str]] = []
    if r in ("admin", "design", "sales"):
        pages.append(("setup", "Setup"))
    if r in ("admin", "sales"):
        pages.append(("sales", "Sales"))
    if r in ("admin", "design"):
        pages.append(("design", "Design"))
    return pages


def default_nav_page(role: str) -> str:
    r = normalize_role(role)
    if r == "design":
        return "design"
    if r == "sales":
        return "sales"
    return "setup"


def can_write(role: str, module: str) -> bool:
    """Ghi dữ liệu theo role."""
    r = normalize_role(role)
    if r == "admin":
        return True
    if module == MOD_SETUP_PERMISSIONS:
        return False
    if module == MOD_SETUP_ACCOUNT:
        return r == "design"
    if module in _DESIGN_MODULES:
        return r == "design"
    if module == MOD_SALES:
        return r == "sales"
    return False


def can_manage_npl_types(role: str) -> bool:
    """Thêm / sửa / xóa loại NPL theo dõi — chỉ admin (tránh hư cấu hình team)."""
    return normalize_role(role) == "admin"

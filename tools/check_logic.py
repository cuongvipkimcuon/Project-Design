"""Kiem tra logic auth / phan quyen / duyet tai khoan."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.auth import AuthService
from core.permissions import can_write, normalize_role
from core.supabase_service import APPROVAL_PENDING


def ok(msg: str) -> None:
    print(f"  OK  {msg}")


def fail(msg: str) -> None:
    print(f"  FAIL {msg}")
    raise SystemExit(1)


def main() -> None:
    auth = AuthService()
    print("=== Auth / Supabase ===")
    print(f"uses_supabase: {auth.uses_supabase}")

    # Admin login
    try:
        admin = auth.authenticate("admin", "1")
    except ValueError as exc:
        fail(f"admin login: {exc}")
    if not admin:
        fail("admin login returned None")
    if admin.get("role") != "admin":
        fail(f"admin role={admin.get('role')}")
    if admin.get("approval_status") != "approved":
        fail(f"admin status={admin.get('approval_status')}")
    ok(f"admin login @{admin['username']} role={admin['role']}")

    # Permissions
    print("\n=== Permissions ===")
    if not can_write("admin", "design_planning"):
        fail("admin should write planning")
    ok("admin can write planning")
    if can_write("design", "setup_permissions"):
        fail("design should not access permissions write")
    ok("design blocked from permissions admin UI access check")
    if not can_write("design", "design_planning"):
        fail("design should write planning")
    ok("design can write planning")
    if can_write("sales", "design_planning"):
        fail("sales should not write planning")
    ok("sales cannot write planning")

    # Pending users list (admin API)
    print("\n=== Pending approvals ===")
    pending = auth.list_pending_users()
    print(f"pending count: {len(pending)}")
    ok("list_pending_users works")

    # Register flow creates pending (dry check message only if user exists skip)
    test_user = "test_logic_user_xyz"
    try:
        auth.register(test_user, "secret99", "Test User")
        ok(f"register {test_user} -> pending")
        try:
            auth.authenticate(test_user, "secret99")
            fail("pending user should not login")
        except ValueError as exc:
            if "duyet" in str(exc).lower() or "duyệt" in str(exc).lower() or "admin" in str(exc).lower():
                ok(f"pending blocked: {exc}")
            else:
                fail(f"wrong error: {exc}")
        # Approve
        prof = auth.supabase.get_profile_by_username(test_user)
        if prof:
            auth.approve_user("admin", prof["id"], role="design")
            ok("approve user")
            u2 = auth.authenticate(test_user, "secret99")
            if u2 and u2.get("approval_status") == "approved":
                ok("login after approve")
            else:
                fail("login after approve failed")
    except ValueError as e:
        if "ton tai" in str(e).lower() or "tồn tại" in str(e).lower():
            print(f"  SKIP register (user exists): {e}")
        else:
            fail(f"register: {e}")

    print("\n=== All logic checks passed ===")


if __name__ == "__main__":
    main()

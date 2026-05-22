"""
Tao super admin dau tien (mac dinh: admin / 1).

Chay:
  python tools/setup_supabase.py   # neu chua co cot approval_status
  python tools/create_super_admin.py
  python tools/create_super_admin.py admin 1 "Admin"
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.auth import AuthService  # noqa: E402


def main() -> None:
    username = sys.argv[1] if len(sys.argv) > 1 else "admin"
    password = sys.argv[2] if len(sys.argv) > 2 else "1"
    display = sys.argv[3] if len(sys.argv) > 3 else "Administrator"

    auth = AuthService()
    try:
        profile = auth.ensure_super_admin(username, password, display)
    except Exception as exc:
        print(f"Loi: {exc}")
        sys.exit(1)

    print(
        f"Super admin OK: @{profile['username']} role={profile['role']} "
        f"status={profile.get('approval_status')}"
    )


if __name__ == "__main__":
    main()

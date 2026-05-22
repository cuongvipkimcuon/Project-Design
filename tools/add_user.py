"""
Thêm user vào database (không qua giao diện app).

Ví dụ:
  python tools/add_user.py admin secret123 "Nguyễn Văn A" [role]
  role: admin | design | sales (mặc định design)
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.database import HubDatabase  # noqa: E402


def main() -> None:
    if len(sys.argv) < 3:
        print("Usage: python tools/add_user.py <username> <password> [display_name] [role]")
        sys.exit(1)
    username = sys.argv[1]
    password = sys.argv[2]
    display = sys.argv[3] if len(sys.argv) > 3 else username
    role = sys.argv[4] if len(sys.argv) > 4 else "admin"
    db = HubDatabase()
    if db.get_user_by_username(username):
        print(f"User '{username}' đã tồn tại.")
        sys.exit(1)
    uid = db.create_user(username, password, display, role=role)
    print(f"Created user id={uid} username={username}")


if __name__ == "__main__":
    main()

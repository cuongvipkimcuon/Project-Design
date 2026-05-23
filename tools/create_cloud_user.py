"""
Admin tao user cloud truc tiep (khong qua form Dang ky — tranh rate limit Supabase).

Vi du:
  python tools/create_cloud_user.py nghia12 matkhau123 "Nghia Nguyen" design
  python tools/create_cloud_user.py nghia12 matkhau123 "Nghia Nguyen" design pending
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.bootstrap_admin import bootstrap_auth_user  # noqa: E402


def main() -> None:
    if len(sys.argv) < 3:
        print(
            "Usage: python tools/create_cloud_user.py <username> <password> "
            '[display_name] [role] [approval: approved|pending]'
        )
        sys.exit(1)
    username = sys.argv[1]
    password = sys.argv[2]
    display = sys.argv[3] if len(sys.argv) > 3 else username
    role = sys.argv[4] if len(sys.argv) > 4 else "design"
    approval = sys.argv[5] if len(sys.argv) > 5 else "approved"
    active = approval == "approved"
    try:
        profile = bootstrap_auth_user(
            username,
            password,
            display,
            role=role,
            approval_status=approval,
            is_active=active,
        )
    except Exception as exc:
        print(f"Loi: {exc}")
        sys.exit(1)
    print(
        f"OK: @{profile['username']} role={profile['role']} "
        f"status={profile.get('approval_status')} active={profile.get('is_active')}"
    )


if __name__ == "__main__":
    main()

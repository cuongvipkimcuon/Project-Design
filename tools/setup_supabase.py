"""
Thiết lập schema Supabase tự động — không cần copy SQL vào Dashboard.

Cấu hình .env (một trong hai cách):

  SUPABASE_DB_PASSWORD=<mật khẩu Database từ Supabase → Settings → Database>

hoặc:

  DATABASE_URL=postgresql://postgres:...@db.<project-ref>.supabase.co:5432/postgres

Chạy:
  python tools/setup_supabase.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.supabase_config import get_database_url, supabase_enabled  # noqa: E402
from core.supabase_migrate import run_all_migrations  # noqa: E402


def main() -> None:
    if not supabase_enabled():
        print("Thiếu SUPABASE_URL / SUPABASE_ANON_KEY trong .env")
        sys.exit(1)

    if not get_database_url():
        print(
            "Thiếu kết nối Postgres.\n\n"
            "Vào Supabase Dashboard → Project Settings → Database:\n"
            "  • Copy Database password → thêm vào .env:\n"
            "      SUPABASE_DB_PASSWORD=your-password\n\n"
            "  hoặc copy Connection string (URI) → .env:\n"
            "      DATABASE_URL=postgresql://...\n"
        )
        sys.exit(1)

    try:
        run_all_migrations(verbose=True)
    except Exception as exc:
        print(f"\nError: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()

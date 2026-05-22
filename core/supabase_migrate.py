"""Chạy file SQL trong supabase/ qua kết nối Postgres trực tiếp."""

from __future__ import annotations

from pathlib import Path

from core.supabase_config import SUPABASE_SQL_DIR, get_database_url


def list_migration_files() -> list[Path]:
    if not SUPABASE_SQL_DIR.is_dir():
        return []
    return sorted(SUPABASE_SQL_DIR.glob("*.sql"))


def run_sql_file(conn, path: Path, *, verbose: bool = True) -> None:
    sql = path.read_text(encoding="utf-8")
    if verbose:
        print(f"  >> {path.name}")
    conn.execute(sql)


def run_all_migrations(*, verbose: bool = True) -> list[str]:
    """
    Kết nối Supabase Postgres và chạy lần lượt 001_*.sql, 002_*.sql, ...
    Trả về danh sách file đã chạy.
    """
    url = get_database_url()
    if not url:
        raise RuntimeError(
            "Chưa có kết nối Postgres. Thêm vào .env một trong hai:\n"
            "  DATABASE_URL=postgresql://postgres:...@db.<ref>.supabase.co:5432/postgres\n"
            "  SUPABASE_DB_PASSWORD=<mật khẩu database từ Supabase Dashboard>"
        )

    files = list_migration_files()
    if not files:
        raise RuntimeError(f"Không tìm thấy file .sql trong {SUPABASE_SQL_DIR}")

    try:
        import psycopg
    except ImportError as exc:
        raise RuntimeError("Cài psycopg: pip install 'psycopg[binary]'") from exc

    ran: list[str] = []
    if verbose:
        print("Connecting to Supabase Postgres...")

    with psycopg.connect(url, autocommit=True) as conn:
        for path in files:
            run_sql_file(conn, path, verbose=verbose)
            ran.append(path.name)

    if verbose:
        print(f"Done - ran {len(ran)} migration file(s).")
    return ran


def check_schema_ready() -> bool:
    """Kiểm tra bảng user_settings đã tồn tại chưa."""
    url = get_database_url()
    if not url:
        return False
    try:
        import psycopg

        with psycopg.connect(url) as conn:
            row = conn.execute(
                """
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = 'public' AND table_name = 'user_settings'
                """
            ).fetchone()
            return row is not None
    except Exception:
        return False

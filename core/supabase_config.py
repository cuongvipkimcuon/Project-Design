"""Cấu hình Supabase — đọc từ biến môi trường / .env."""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import quote_plus

from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parents[1]
SUPABASE_SQL_DIR = _ROOT / "supabase"
load_dotenv(_ROOT / ".env")

SUPABASE_URL = os.getenv("SUPABASE_URL", "https://ynvzumtxlqhcelxzjaae.supabase.co").strip()
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY", "").strip()
AUTH_EMAIL_DOMAIN = os.getenv("AUTH_EMAIL_DOMAIN", "dghub.local").strip()
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
SUPABASE_DB_PASSWORD = os.getenv("SUPABASE_DB_PASSWORD", "").strip()


def auth_email_for_username(username: str) -> str:
    return f"{username.strip().lower()}@{AUTH_EMAIL_DOMAIN}"


def username_from_auth_email(email: str) -> str:
    text = (email or "").strip().lower()
    suffix = f"@{AUTH_EMAIL_DOMAIN}"
    if text.endswith(suffix):
        return text[: -len(suffix)]
    if "@" in text:
        return text.split("@", 1)[0]
    return text


def supabase_enabled() -> bool:
    return bool(SUPABASE_URL and SUPABASE_ANON_KEY)


def project_ref() -> str:
    host = SUPABASE_URL.replace("https://", "").replace("http://", "").strip("/")
    return host.split(".")[0] if host else ""


def get_database_url() -> str:
    """URL Postgres trực tiếp — dùng cho migration DDL."""
    if DATABASE_URL:
        return DATABASE_URL
    if SUPABASE_DB_PASSWORD and SUPABASE_URL:
        ref = project_ref()
        if ref:
            pwd = quote_plus(SUPABASE_DB_PASSWORD)
            return f"postgresql://postgres:{pwd}@db.{ref}.supabase.co:5432/postgres"
    return ""


def database_configured() -> bool:
    return bool(get_database_url())

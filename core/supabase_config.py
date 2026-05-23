"""Cấu hình Supabase — đọc từ biến môi trường / .env."""

from __future__ import annotations

import os
import re
from urllib.parse import quote_plus

from dotenv import load_dotenv

from core.paths import app_dir, resource_dir
from core.utils import normalize_text

_ROOT = app_dir()
_RESOURCE = resource_dir()
SUPABASE_SQL_DIR = _RESOURCE / "supabase"
load_dotenv(_ROOT / ".env")

SUPABASE_URL = os.getenv("SUPABASE_URL", "https://ynvzumtxlqhcelxzjaae.supabase.co").strip()
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY", "").strip()
DEFAULT_AUTH_EMAIL_DOMAIN = "dghouse.app"
LEGACY_AUTH_EMAIL_DOMAINS = ("dghub.local",)
AUTH_EMAIL_DOMAIN = os.getenv("AUTH_EMAIL_DOMAIN", DEFAULT_AUTH_EMAIL_DOMAIN).strip() or DEFAULT_AUTH_EMAIL_DOMAIN
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
SUPABASE_DB_PASSWORD = os.getenv("SUPABASE_DB_PASSWORD", "").strip()


def _sanitize_email_local(username: str) -> str:
    text = username.strip().lower()
    text = re.sub(r"[^a-z0-9._+-]", "", text)
    return text or "user"


def _auth_email_domains() -> tuple[str, ...]:
    domains: list[str] = []
    for domain in (AUTH_EMAIL_DOMAIN, *LEGACY_AUTH_EMAIL_DOMAINS):
        d = normalize_text(domain)
        if d and d not in domains:
            domains.append(d)
    return tuple(domains)


def auth_email_for_username(username: str) -> str:
    return f"{_sanitize_email_local(username)}@{AUTH_EMAIL_DOMAIN}"


def auth_emails_for_login(username: str) -> list[str]:
    local = _sanitize_email_local(username)
    return [f"{local}@{domain}" for domain in _auth_email_domains()]


def username_from_auth_email(email: str) -> str:
    text = (email or "").strip().lower()
    for domain in _auth_email_domains():
        suffix = f"@{domain}"
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

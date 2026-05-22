"""Kiem tra ket noi Supabase (Postgres + REST)."""
from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import httpx

from core.supabase_config import (
    SUPABASE_ANON_KEY,
    SUPABASE_URL,
    get_database_url,
    project_ref,
    supabase_enabled,
)
from core.supabase_migrate import check_schema_ready


def main() -> None:
    print("=== Config ===")
    print("project ref (URL):", project_ref())
    print("supabase API enabled:", supabase_enabled())
    print("database URL set:", bool(get_database_url()))

    try:
        payload = SUPABASE_ANON_KEY.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        jwt = json.loads(base64.urlsafe_b64decode(payload))
        ref = jwt.get("ref")
        print("anon JWT project ref:", ref)
        print("JWT ref matches URL:", ref == project_ref())
    except Exception as exc:
        print("JWT decode fail:", exc)

    print("\n=== Postgres ===")
    try:
        import psycopg

        with psycopg.connect(get_database_url(), connect_timeout=10) as conn:
            conn.execute("SELECT 1")
            tables = conn.execute(
                """
                SELECT table_name FROM information_schema.tables
                WHERE table_schema = 'public'
                  AND table_name IN ('profiles', 'user_settings', 'user_datasets', 'team_datasets')
                ORDER BY 1
                """
            ).fetchall()
        print("connect: OK")
        print("schema tables:", [t[0] for t in tables])
        print("schema ready:", check_schema_ready())
    except Exception as exc:
        print("connect: FAIL")
        print(type(exc).__name__ + ":", str(exc)[:200])

    print("\n=== Supabase REST (anon) ===")
    try:
        r = httpx.get(
            SUPABASE_URL + "/rest/v1/profiles?select=id&limit=1",
            headers={
                "apikey": SUPABASE_ANON_KEY,
                "Authorization": "Bearer " + SUPABASE_ANON_KEY,
            },
            timeout=10,
        )
        if r.status_code < 400:
            print("profiles API: OK (status", r.status_code, ")")
        else:
            print("profiles API: FAIL status", r.status_code, r.text[:150])
    except Exception as exc:
        print("REST: FAIL", type(exc).__name__, str(exc)[:150])


if __name__ == "__main__":
    main()

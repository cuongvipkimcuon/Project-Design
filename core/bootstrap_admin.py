"""Tao user Auth + profiles qua Postgres (khong qua API sign_up — tranh rate limit)."""

from __future__ import annotations

from core.permissions import normalize_role
from core.supabase_config import AUTH_EMAIL_DOMAIN, get_database_url


def _esc(text: str) -> str:
    return text.replace("'", "''")


def bootstrap_auth_user(
    username: str,
    password: str,
    display_name: str = "",
    *,
    role: str = "design",
    approval_status: str = "approved",
    is_active: bool = True,
) -> dict[str, str | bool]:
    url = get_database_url()
    if not url:
        raise RuntimeError("Can DATABASE_URL trong .env")

    uname_raw = username.strip().lower()
    if len(uname_raw) < 2:
        raise ValueError("Username phai co it nhat 2 ky tu.")
    if len(password) < 6:
        raise ValueError("Mat khau toi thieu 6 ky tu.")

    email = f"{uname_raw}@{AUTH_EMAIL_DOMAIN}"
    uname = _esc(uname_raw)
    dname = _esc(display_name.strip() or uname_raw)
    pwd = _esc(password)
    em = _esc(email)
    role_sql = _esc(normalize_role(role))
    status_sql = _esc(approval_status.strip() or "approved")
    active_sql = "TRUE" if is_active else "FALSE"

    import psycopg

    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

        conn.execute(
            f"""
            DO $$
            DECLARE
              uid uuid;
              inst_id uuid;
            BEGIN
              SELECT id INTO inst_id FROM auth.instances LIMIT 1;
              IF inst_id IS NULL THEN
                inst_id := '00000000-0000-0000-0000-000000000000'::uuid;
              END IF;

              SELECT id INTO uid FROM auth.users WHERE lower(email) = lower('{em}');

              IF uid IS NULL THEN
                uid := gen_random_uuid();
                INSERT INTO auth.users (
                  instance_id, id, aud, role, email, encrypted_password,
                  email_confirmed_at, invited_at, confirmation_token,
                  recovery_token, email_change_token_new, email_change,
                  raw_app_meta_data, raw_user_meta_data, created_at, updated_at,
                  is_super_admin, is_anonymous
                ) VALUES (
                  inst_id, uid, 'authenticated', 'authenticated', '{em}',
                  crypt('{pwd}', gen_salt('bf')),
                  NOW(), NOW(), '', '', '', '',
                  '{{"provider":"email","providers":["email"]}}'::jsonb,
                  jsonb_build_object('username', '{uname}', 'display_name', '{dname}'),
                  NOW(), NOW(),
                  FALSE, FALSE
                );
              ELSE
                UPDATE auth.users
                SET encrypted_password = crypt('{pwd}', gen_salt('bf')),
                    email_confirmed_at = COALESCE(email_confirmed_at, NOW()),
                    updated_at = NOW()
                WHERE id = uid;
              END IF;

              INSERT INTO public.profiles (id, username, display_name, role, is_active, approval_status)
              VALUES (uid, '{uname}', '{dname}', '{role_sql}', {active_sql}, '{status_sql}')
              ON CONFLICT (id) DO UPDATE SET
                username = EXCLUDED.username,
                display_name = EXCLUDED.display_name,
                role = EXCLUDED.role,
                is_active = EXCLUDED.is_active,
                approval_status = EXCLUDED.approval_status;
            END $$;
            """
        )

        row = conn.execute(
            """
            SELECT id::text, username, display_name, role, is_active, approval_status
            FROM public.profiles
            WHERE lower(username) = lower(%s)
            """,
            (uname_raw,),
        ).fetchone()

    if not row:
        raise RuntimeError("Khong tao duoc user trong profiles")
    return {
        "id": str(row[0]),
        "username": str(row[1]),
        "display_name": str(row[2]),
        "role": str(row[3]),
        "is_active": bool(row[4]),
        "approval_status": str(row[5]),
    }


def bootstrap_super_admin(
    username: str = "admin",
    password: str = "1",
    display_name: str = "Administrator",
) -> dict[str, str | bool]:
    return bootstrap_auth_user(
        username,
        password,
        display_name,
        role="admin",
        approval_status="approved",
        is_active=True,
    )

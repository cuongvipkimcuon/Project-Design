"""Tao super admin qua Postgres (ho tro mat khau ngan)."""

from __future__ import annotations

from core.supabase_config import AUTH_EMAIL_DOMAIN, get_database_url


def _esc(text: str) -> str:
    return text.replace("'", "''")


def bootstrap_super_admin(
    username: str = "admin",
    password: str = "1",
    display_name: str = "Administrator",
) -> dict[str, str | bool]:
    url = get_database_url()
    if not url:
        raise RuntimeError("Can DATABASE_URL trong .env")

    email = f"{username.strip().lower()}@{AUTH_EMAIL_DOMAIN}"
    uname = _esc(username.strip().lower())
    dname = _esc(display_name.strip() or username.strip())
    pwd = _esc(password)
    em = _esc(email)

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
              VALUES (uid, '{uname}', '{dname}', 'admin', TRUE, 'approved')
              ON CONFLICT (id) DO UPDATE SET
                username = EXCLUDED.username,
                display_name = EXCLUDED.display_name,
                role = 'admin',
                is_active = TRUE,
                approval_status = 'approved';
            END $$;
            """
        )

        row = conn.execute(
            """
            SELECT id::text, username, display_name, role, is_active, approval_status
            FROM public.profiles
            WHERE lower(username) = lower(%s)
            """,
            (uname,),
        ).fetchone()

    if not row:
        raise RuntimeError("Khong tao duoc admin trong profiles")
    return {
        "id": str(row[0]),
        "username": str(row[1]),
        "display_name": str(row[2]),
        "role": str(row[3]),
        "is_active": bool(row[4]),
        "approval_status": str(row[5]),
    }

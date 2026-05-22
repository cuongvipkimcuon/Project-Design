-- Duyet tai khoan: pending | approved | rejected

ALTER TABLE public.profiles
    ADD COLUMN IF NOT EXISTS approval_status TEXT NOT NULL DEFAULT 'approved';

ALTER TABLE public.profiles DROP CONSTRAINT IF EXISTS profiles_approval_status_check;
ALTER TABLE public.profiles
    ADD CONSTRAINT profiles_approval_status_check
    CHECK (approval_status IN ('pending', 'approved', 'rejected'));

UPDATE public.profiles
SET approval_status = 'approved'
WHERE approval_status IS NULL OR approval_status = '';

CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER SET search_path = public
AS $$
BEGIN
    INSERT INTO public.profiles (id, username, display_name, role, is_active, approval_status)
    VALUES (
        NEW.id,
        COALESCE(NEW.raw_user_meta_data->>'username', split_part(NEW.email, '@', 1)),
        COALESCE(NEW.raw_user_meta_data->>'display_name', split_part(NEW.email, '@', 1)),
        'design',
        FALSE,
        'pending'
    )
    ON CONFLICT (id) DO NOTHING;
    RETURN NEW;
END;
$$;

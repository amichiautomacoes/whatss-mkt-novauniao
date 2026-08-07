from supabase import Client, create_client

from app.config import get_settings


def get_supabase_client() -> Client:
    settings = get_settings()
    if not settings.supabase_url or not settings.supabase_service_role_key:
        raise RuntimeError("Supabase credentials are missing in .env")

    return create_client(settings.supabase_url, settings.supabase_service_role_key)

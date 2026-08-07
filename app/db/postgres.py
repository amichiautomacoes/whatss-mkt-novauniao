import psycopg
from psycopg.rows import dict_row

from app.config import get_settings


def get_postgres_connection() -> psycopg.Connection:
    settings = get_settings()
    if not settings.supabase_database_url:
        raise RuntimeError("SUPABASE_DATABASE_URL is missing in .env")

    return psycopg.connect(settings.supabase_database_url, row_factory=dict_row)

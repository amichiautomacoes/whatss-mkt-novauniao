import httpx
import psycopg
import pytest
from redis import Redis

from app.config import get_settings


@pytest.fixture(autouse=True)
def offline_environment(monkeypatch):
    def forbid_external_access(*args, **kwargs):
        raise AssertionError("Tests must not connect to production services")

    monkeypatch.setattr(psycopg, "connect", forbid_external_access)
    monkeypatch.setattr(httpx.Client, "send", forbid_external_access)
    monkeypatch.setattr(Redis, "from_url", forbid_external_access)
    for key, value in {
        "SUPABASE_DATABASE_URL": "",
        "SUPABASE_SCHEMA": "mkt_novauniao",
        "REDIS_URL": "redis://localhost:6379/15",
        "REDIS_QUEUE_PREFIX": "whatsapp_test",
        "REDIS_MAX_ATTEMPTS": "3",
        "REDIS_RETRY_DELAY_SECONDS": "300",
        "REDIS_VISIBILITY_TIMEOUT_SECONDS": "300",
        "DEFAULT_SEND_DELAY_SECONDS": "0",
        "CAMPAIGN_TIMEZONE": "America/Sao_Paulo",
        "WHATSAPP_CAMPAIGN_NAME": "Campanha 2",
        "WHATSAPP_OPENED_FROM": "2026-11-17",
        "WHATSAPP_SEND_TIME": "14:00",
        "WHATSAPP_SCHEDULE_ENABLED": "true",
        "WHATSAPP_SCHEDULE_DRY_RUN": "false",
        "WHATSAPP_SCHEDULE_LIMIT": "500",
        "WORKER_INTERVAL_SECONDS": "60",
        "WORKER_BATCH_SIZE": "1",
        "EVOLUTION_API_URL": "https://evolution.test",
        "EVOLUTION_API_KEY": "test-key",
    }.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()

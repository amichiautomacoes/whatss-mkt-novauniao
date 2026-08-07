from functools import lru_cache

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    supabase_url: str = Field(default="", alias="SUPABASE_URL")
    supabase_service_role_key: str = Field(
        default="",
        validation_alias=AliasChoices("SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_SECRET_KEY"),
    )
    supabase_database_url: str = Field(default="", alias="SUPABASE_DATABASE_URL")
    supabase_schema: str = Field(default="public", alias="SUPABASE_SCHEMA")

    evolution_api_url: str = Field(
        default="",
        validation_alias=AliasChoices("EVOLUTION_API_URL", "EVOLUTION_BASE_URL"),
    )
    evolution_api_key: str = Field(default="", alias="EVOLUTION_API_KEY")
    evolution_api_version: str = Field(default="", alias="EVOLUTION_API_VERSION")
    evolution_instance: str = Field(default="", alias="EVOLUTION_INSTANCE")
    dispatch_webhook_token: str = Field(
        default="",
        validation_alias=AliasChoices("DISPATCH_WEBHOOK_TOKEN", "EVOLUTION_TOKEN"),
    )

    app_env: str = Field(default="local", alias="APP_ENV")
    app_public_url: str = Field(default="", alias="APP_PUBLIC_URL")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    default_send_delay_seconds: int = Field(default=60, alias="DEFAULT_SEND_DELAY_SECONDS")
    default_batch_size: int = Field(default=20, alias="DEFAULT_BATCH_SIZE")
    campaign_timezone: str = Field(default="America/Sao_Paulo", alias="CAMPAIGN_TIMEZONE")
    morning_send_start: str = Field(default="09:00", alias="MORNING_SEND_START")
    afternoon_send_start: str = Field(default="14:00", alias="AFTERNOON_SEND_START")

    redis_url: str = Field(default="", alias="REDIS_URL")
    redis_queue_prefix: str = Field(default="whatsapp_mkt", alias="REDIS_QUEUE_PREFIX")
    redis_visibility_timeout_seconds: int = Field(
        default=300,
        alias="REDIS_VISIBILITY_TIMEOUT_SECONDS",
    )
    redis_retry_delay_seconds: int = Field(default=300, alias="REDIS_RETRY_DELAY_SECONDS")
    redis_max_attempts: int = Field(default=3, alias="REDIS_MAX_ATTEMPTS")


@lru_cache
def get_settings() -> Settings:
    return Settings()

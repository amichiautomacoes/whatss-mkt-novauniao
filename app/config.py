from datetime import date, time
from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    supabase_database_url: str = Field(default="", alias="SUPABASE_DATABASE_URL")
    supabase_schema: str = Field(default="mkt_novauniao", alias="SUPABASE_SCHEMA")

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

    whatsapp_campaign_name: str = Field(default="", alias="WHATSAPP_CAMPAIGN_NAME")
    whatsapp_opened_from: date = Field(default=date(2026, 11, 17), alias="WHATSAPP_OPENED_FROM")
    whatsapp_send_time: str = Field(default="14:00", alias="WHATSAPP_SEND_TIME")
    whatsapp_schedule_enabled: bool = Field(default=True, alias="WHATSAPP_SCHEDULE_ENABLED")
    whatsapp_schedule_dry_run: bool = Field(default=False, alias="WHATSAPP_SCHEDULE_DRY_RUN")
    whatsapp_schedule_limit: int = Field(default=500, alias="WHATSAPP_SCHEDULE_LIMIT", ge=1)
    worker_interval_seconds: int = Field(default=60, alias="WORKER_INTERVAL_SECONDS", ge=1, le=60)
    worker_batch_size: int = Field(default=1, alias="WORKER_BATCH_SIZE", ge=1, le=20)

    @field_validator("whatsapp_send_time")
    @classmethod
    def validate_send_time(cls, value: str) -> str:
        if len(value) != 5:
            raise ValueError("WHATSAPP_SEND_TIME must use HH:MM")
        parsed = time.fromisoformat(value)
        return parsed.strftime("%H:%M")

    @field_validator("whatsapp_schedule_limit", mode="before")
    @classmethod
    def default_empty_schedule_limit(cls, value):
        return 500 if value == "" else value

    google_service_account_file: Path = Field(
        default=Path("mkt-novauniao-d64a259b4a40.json"),
        alias="GOOGLE_SERVICE_ACCOUNT_FILE",
    )
    google_service_account_json: str = Field(
        default="",
        alias="GOOGLE_SERVICE_ACCOUNT_JSON",
    )
    google_service_account_json_base64: str = Field(
        default="",
        alias="GOOGLE_SERVICE_ACCOUNT_JSON_BASE64",
    )
    whatsapp_schedule_spreadsheet_id: str = Field(
        default="",
        alias="WHATSAPP_SCHEDULE_SPREADSHEET_ID",
    )
    whatsapp_schedule_spreadsheet_name: str = Field(
        default="Cronograma Whatsapp MKT",
        alias="WHATSAPP_SCHEDULE_SPREADSHEET_NAME",
    )
    whatsapp_schedule_sheet_name: str = Field(
        default="Agenda Whatsapp",
        alias="WHATSAPP_SCHEDULE_SHEET_NAME",
    )

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

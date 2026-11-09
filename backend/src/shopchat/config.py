"""Typed application settings, loaded from the environment or a local .env file."""

from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    database_owner_url: str
    redis_url: str
    app_url: str

    # Hard switch: no OpenAI call can happen while this is false.
    llm_calls_enabled: bool = False
    voice_enabled: bool = False

    openai_api_key: SecretStr | None = None
    openai_model_fast: str | None = None
    openai_model_smart: str | None = None
    openai_model_embedding: str | None = None
    openai_model_stt: str | None = None
    openai_model_tts: str | None = None

    shopify_api_key: str | None = None
    shopify_api_secret: SecretStr | None = None
    shopify_api_version: str = "2026-10"

    token_encryption_key: SecretStr | None = None
    widget_token_secret: SecretStr | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()

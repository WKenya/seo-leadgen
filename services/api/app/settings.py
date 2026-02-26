from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "seo-lead-api"
    environment: str = "dev"
    database_url: str = Field(
        default="postgresql+psycopg://postgres:postgres@db:5432/seo_lead",
        alias="DATABASE_URL",
    )
    redis_url: str = Field(default="redis://redis:6379/0", alias="REDIS_URL")
    artifacts_root: str = "/data/artifacts"
    artifacts_basic_auth_user: str = Field(default="", alias="ARTIFACTS_BASIC_AUTH_USER")
    artifacts_basic_auth_pass: str = Field(default="", alias="ARTIFACTS_BASIC_AUTH_PASS")
    webhook_shared_secret: str = Field(default="", alias="WEBHOOK_SHARED_SECRET")
    webhook_signature_secret: str = Field(default="", alias="WEBHOOK_SIGNATURE_SECRET")
    webhook_signature_tolerance_seconds: int = Field(default=300, alias="WEBHOOK_SIGNATURE_TOLERANCE_SECONDS")
    postmark_webhook_token: str = Field(default="", alias="POSTMARK_WEBHOOK_TOKEN")
    mailgun_webhook_signing_key: str = Field(default="", alias="MAILGUN_WEBHOOK_SIGNING_KEY")
    mailgun_webhook_signature_tolerance_seconds: int = Field(
        default=300,
        alias="MAILGUN_WEBHOOK_SIGNATURE_TOLERANCE_SECONDS",
    )
    daily_send_cap: int = Field(default=5, alias="DAILY_SEND_CAP")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()

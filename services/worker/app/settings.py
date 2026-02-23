from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "seo-lead-worker"
    database_url: str = Field(
        default="postgresql+psycopg://postgres:postgres@db:5432/seo_lead",
        alias="DATABASE_URL",
    )
    redis_url: str = Field(default="redis://redis:6379/0", alias="REDIS_URL")
    google_places_api_key: str = Field(default="", alias="GOOGLE_PLACES_API_KEY")
    sender_name: str = Field(default="Website Fixer", alias="SENDER_NAME")
    sender_email: str = Field(default="noreply@example.com", alias="SENDER_EMAIL")
    physical_address: str = Field(default="PO Box 123, Cleveland, OH 44101", alias="PHYSICAL_ADDRESS")
    opt_out_instructions: str = Field(default='Reply "unsubscribe"', alias="OPT_OUT_INSTRUCTIONS")
    crawl_max_pages: int = Field(default=10, alias="CRAWL_MAX_PAGES")
    crawl_delay_seconds: float = Field(default=1.0, alias="CRAWL_DELAY_SECONDS")
    audit_lighthouse_url: str = Field(default="http://audit:8081/run", alias="AUDIT_LIGHTHOUSE_URL")
    daily_send_cap: int = Field(default=5, alias="DAILY_SEND_CAP")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()

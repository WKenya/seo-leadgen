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
    artifacts_root: str = Field(default="/data/artifacts", alias="ARTIFACTS_ROOT")
    google_places_api_key: str = Field(default="", alias="GOOGLE_PLACES_API_KEY")
    notion_token: str = Field(default="", alias="NOTION_TOKEN")
    notion_database_id: str = Field(default="", alias="NOTION_DATABASE_ID")
    public_api_base_url: str = Field(default="", alias="PUBLIC_API_BASE_URL")
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    openai_model: str = Field(default="", alias="OPENAI_MODEL")
    openai_base_url: str = Field(default="https://api.openai.com/v1", alias="OPENAI_BASE_URL")
    gmail_oauth_client_id: str = Field(default="", alias="GMAIL_OAUTH_CLIENT_ID")
    gmail_oauth_client_secret: str = Field(default="", alias="GMAIL_OAUTH_CLIENT_SECRET")
    gmail_oauth_refresh_token: str = Field(default="", alias="GMAIL_OAUTH_REFRESH_TOKEN")
    sender_name: str = Field(default="Website Fixer", alias="SENDER_NAME")
    sender_email: str = Field(default="noreply@example.com", alias="SENDER_EMAIL")
    physical_address: str = Field(default="PO Box 123, Cleveland, OH 44101", alias="PHYSICAL_ADDRESS")
    opt_out_instructions: str = Field(default='Reply "unsubscribe"', alias="OPT_OUT_INSTRUCTIONS")
    crawl_max_pages: int = Field(default=10, alias="CRAWL_MAX_PAGES")
    crawl_delay_seconds: float = Field(default=1.0, alias="CRAWL_DELAY_SECONDS")
    audit_max_broken_link_issues: int = Field(default=25, alias="AUDIT_MAX_BROKEN_LINK_ISSUES")
    audit_lighthouse_url: str = Field(default="http://audit:8081/run", alias="AUDIT_LIGHTHOUSE_URL")
    daily_send_cap: int = Field(default=5, alias="DAILY_SEND_CAP")
    discovery_city: str = Field(default="Cleveland, OH", alias="DISCOVERY_CITY")
    discovery_categories_csv: str = Field(default="HVAC,dentist", alias="DISCOVERY_CATEGORIES")
    discovery_radius_meters: int = Field(default=15000, alias="DISCOVERY_RADIUS_METERS")
    discovery_limit_per_category: int = Field(default=20, alias="DISCOVERY_LIMIT_PER_CATEGORY")
    discovery_schedule_hour_utc: int = Field(default=11, alias="DISCOVERY_SCHEDULE_HOUR_UTC")
    discovery_schedule_minute_utc: int = Field(default=15, alias="DISCOVERY_SCHEDULE_MINUTE_UTC")

    @property
    def discovery_categories(self) -> list[str]:
        return [item.strip() for item in self.discovery_categories_csv.split(",") if item.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()

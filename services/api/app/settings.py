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


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Ukrainian Legal AI Assistant"
    app_env: str = "local"
    database_url: str = "postgresql+psycopg://jur_user:jur_password@localhost:5432/jur_db"
    cors_origins: list[str] = Field(default_factory=list)

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


@lru_cache
def get_settings() -> Settings:
    return Settings()

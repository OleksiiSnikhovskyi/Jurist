from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Ukrainian Legal AI Assistant"
    app_env: str = "local"
    postgres_host: str = "localhost"
    postgres_port: int = 5433
    postgres_db: str = "jur_db"
    postgres_user: str = "jur_user"
    postgres_password: str = "jur_password"
    database_url: str = "postgresql+psycopg://jur_user:jur_password@localhost:5433/jur_db"
    test_database_url: str = "sqlite+pysqlite:///:memory:"
    upload_dir: str = "uploads"
    embedding_provider: str = "deterministic"
    embedding_model: str = "local-hash-v1"
    embedding_base_url: str | None = None
    embedding_timeout_seconds: int = 120
    embedding_dimensions: int = 1536
    jur_ollama_base_url: str | None = None
    jur_ollama_model: str = "qwen3:8b"
    jur_ollama_timeout_seconds: int = 900
    jur_ollama_think: bool = False
    jur_ollama_num_ctx: int = 16384
    jur_ollama_num_predict: int = 3072
    cors_origins: list[str] = Field(default_factory=list)

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


@lru_cache
def get_settings() -> Settings:
    return Settings()

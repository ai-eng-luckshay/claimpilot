from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", ".env.dev"),  # .env.dev takes precedence if present
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    google_api_key: str = ""
    langsmith_api_key: str = ""
    langchain_tracing_v2: str = "false"
    langchain_project: str = "claimpilot"

    database_url: str = "postgresql://postgres:postgres@localhost:5432/claimpilot"
    environment: str = "dev"

    api_base_url: str = "http://localhost:8000"
    llm_provider: str = "gemini"  # switch via LLM_PROVIDER env var

    LOGGER_DEBUG_FLAG: str = "N"

    @property
    def is_production(self) -> bool:
        return self.environment == "prod"


@lru_cache
def get_settings() -> Settings:
    return Settings()

settings = get_settings()
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "development"
    database_url: str = (
        "mysql+pymysql://workbench:workbench@127.0.0.1:3306/workbench?charset=utf8mb4"
    )
    model_provider: str = "fake"
    model_api_key: str = ""
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = ""
    llm_timeout_seconds: float = 30.0
    quality_standard_storage_dir: Path = Path("var/quality-standards")

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()

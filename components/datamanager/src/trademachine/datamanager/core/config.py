from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="DATAMANAGER_",
        extra="ignore",
    )

    api_key: str = ""
    host: str = "0.0.0.0"  # noqa: S104
    port: int = 8686

    # Database Settings
    database_url: str = "postgresql://postgres:password@localhost:5433/tradingmonitor"
    debug: bool = False

    @property
    def is_api_key_configured(self) -> bool:
        return bool(self.api_key) and self.api_key != "YOUR_API_KEY_HERE"


settings = Settings()

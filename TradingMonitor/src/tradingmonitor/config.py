from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Database Settings
    database_url: str = Field(
        default="postgresql://postgres:password@localhost:5432/tradingmonitor", alias="DATABASE_URL"
    )

    # TCP Ingestion Server Settings
    server_host: str = Field(default="127.0.0.1", alias="SERVER_HOST")
    server_port: int = Field(default=5555, alias="SERVER_PORT")

    # Dashboard Settings
    dashboard_host: str = Field(default="127.0.0.1", alias="DASHBOARD_HOST")
    dashboard_port: int = Field(default=8000, alias="DASHBOARD_PORT")

    # App Settings
    debug: bool = Field(default=False, alias="DEBUG")
    api_key: str = Field(alias="API_KEY")

    # Telegram Notifications
    enable_notifications: bool = Field(default=False, alias="ENABLE_NOTIFICATIONS")
    telegram_token: str | None = Field(default=None, alias="TELEGRAM_TOKEN")
    telegram_chat_id: str | None = Field(default=None, alias="TELEGRAM_CHAT_ID")
    margin_threshold_pct: float = Field(default=20.0, alias="MARGIN_THRESHOLD_PCT")

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", case_sensitive=False, extra="ignore"
    )


settings = Settings()

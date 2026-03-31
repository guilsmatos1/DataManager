from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Database Settings
    database_url: str = Field(
        default="postgresql://postgres:password@localhost:5432/trademachine.tradingmonitor",
        alias="DATABASE_URL",
    )

    # TCP Ingestion Server Settings
    server_host: str = Field(default="127.0.0.1", alias="SERVER_HOST")
    server_port: int = Field(default=5555, alias="SERVER_PORT")

    # File Paths
    heartbeat_file: str = Field(
        default="/tmp/trademachine.tradingmonitor_heartbeat",
        alias="HEARTBEAT_FILE",
    )
    dead_letter_file: str = Field(
        default="/tmp/trademachine.tradingmonitor_dead_letters.jsonl",
        alias="DEAD_LETTER_FILE",
    )

    # Dashboard Settings
    dashboard_host: str = Field(default="127.0.0.1", alias="DASHBOARD_HOST")
    dashboard_port: int = Field(default=8000, alias="DASHBOARD_PORT")

    # DataManager Integration
    datamanager_url: str = Field(
        default="http://127.0.0.1:8686",
        alias="DATAMANAGER_URL",
    )
    datamanager_api_key: str = Field(
        default="YOUR_API_KEY_HERE",
        alias="DATAMANAGER_API_KEY",
    )
    datamanager_timeout: float = Field(default=30.0, alias="DATAMANAGER_TIMEOUT")

    # App Settings
    debug: bool = Field(default=False, alias="DEBUG")
    api_key: str = Field(alias="API_KEY")

    # Telegram Notifications
    enable_notifications: bool = Field(default=False, alias="ENABLE_NOTIFICATIONS")
    telegram_token: str | None = Field(default=None, alias="TELEGRAM_TOKEN")
    telegram_chat_id: str | None = Field(default=None, alias="TELEGRAM_CHAT_ID")
    margin_threshold_pct: float = Field(default=20.0, alias="MARGIN_THRESHOLD_PCT")
    var_95_threshold: float = Field(default=5.0, alias="VAR_95_THRESHOLD")

    # Performance Drift Settings
    enable_drift_alerts: bool = Field(default=True, alias="ENABLE_DRIFT_ALERTS")
    drift_win_rate_threshold: float = Field(
        default=15.0, alias="DRIFT_WIN_RATE_THRESHOLD"
    )  # Max % drop allowed
    drift_profit_factor_threshold: float = Field(
        default=20.0, alias="DRIFT_PF_THRESHOLD"
    )  # Max % drop allowed
    drift_max_drawdown_multiplier: float = Field(
        default=1.2, alias="DRIFT_DD_MULTIPLIER"
    )  # Max DD relative to backtest
    drift_min_trades: int = Field(
        default=20, alias="DRIFT_MIN_TRADES"
    )  # Min trades before checking

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", case_sensitive=False, extra="ignore"
    )


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance. For production use via dependency injection."""
    return Settings()


# Backward-compatible module-level instance
settings = get_settings()

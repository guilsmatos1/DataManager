"""
Application Configuration
==========================
Centralised configuration using Pydantic Settings for validation.
Loads defaults from code, overridable via .env file.
"""

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_DEFAULT_CSV_COLUMNS = [
    "Combo",
    "Net_Profit",
    "RetDD",
    "Total_Trades",
    "Profit_Factor",
    "Maximum_Drawdown",
    "Relative_Drawdown",
    "Payoff",
    "Avg_Win",
    "Avg_Loss",
    "Avg_Consecutive_Wins",
    "Avg_Consecutive_Losses",
]


class AppConfig(BaseSettings):
    min_assets: int = Field(default=5, ge=1)
    max_assets: int = Field(default=5, ge=1)
    top_n: int = Field(default=10, ge=1)
    max_corr: float = Field(default=0.3, ge=-1.0, le=1.0)
    corr_period: str = Field(default="D")
    rank_by: str = Field(default="RetDD")
    load_workers: int = Field(default=0, ge=0)
    num_workers: int = Field(default=0, ge=0)
    print_results: bool = Field(default=False)
    output_dir: str = Field(default="")
    corr_filter_batch_size: int = Field(default=10000, ge=1)
    matrix_algebra_batch_size: int = Field(default=1000, ge=1)
    csv_columns: list[str] = Field(default_factory=lambda: list(_DEFAULT_CSV_COLUMNS))
    log_path: str = Field(default="projects/portfoliomaster/log.log")
    cache_path: str = Field(default="projects/portfoliomaster/cache.parquet")
    adherence_threshold: float = Field(default=0.80, ge=0.0, le=1.0)
    adherence_pearson: float = Field(default=0.85, ge=-1.0, le=1.0)
    ga_population: int = Field(default=300, ge=10)
    ga_generations: int = Field(default=100, ge=1)
    ga_crossover: float = Field(default=0.7, ge=0.0, le=1.0)
    ga_mutation: float = Field(default=0.2, ge=0.0, le=1.0)

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    @field_validator("corr_period")
    @classmethod
    def validate_corr_period(cls, v: str) -> str:
        allowed = {"H", "D", "W", "M"}
        if v not in allowed:
            raise ValueError(f"corr_period must be one of {allowed}, got '{v}'")
        return v

    @field_validator("rank_by")
    @classmethod
    def validate_rank_by(cls, v: str) -> str:
        allowed = {"RetDD", "NetProfit"}
        if v not in allowed:
            raise ValueError(f"rank_by must be one of {allowed}, got '{v}'")
        return v

    @classmethod
    def from_json(cls, config_path: str = "config.json") -> "AppConfig":
        """Load configuration from a JSON file, falling back to .env and defaults.

        Priority (highest to lowest):
          1. Values present in `config_path` (if the file exists and is valid JSON).
          2. Environment variables and `.env` file (via BaseSettings).
          3. Field defaults defined in this class.

        If the JSON file does not exist the method behaves exactly as `cls()`.
        If the file exists but cannot be parsed, a warning is logged and defaults
        are used — so a missing or malformed file never crashes the application.
        """
        import json
        import logging
        from pathlib import Path

        path = Path(config_path)
        if path.exists():
            try:
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
                return cls(**data)
            except Exception as exc:
                logging.getLogger("trademachine.portfoliomaster.core.config").warning(
                    f"Could not load config from '{config_path}': {exc}. Using defaults."
                )
        return cls()

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="DATAMANAGER_",
    )

    api_key: str = ""
    host: str = "0.0.0.0"
    port: int = 8686

    @property
    def is_api_key_configured(self) -> bool:
        return bool(self.api_key) and self.api_key != "YOUR_API_KEY_HERE"


settings = Settings()

from trademachine.tradingmonitor_storage.config import Settings


def test_database_url_has_no_default():
    field = Settings.model_fields["database_url"]

    assert not field.is_required()
    assert (
        field.default
        == "postgresql://postgres:password@localhost:5432/trademachine.tradingmonitor"
    )


def test_settings_accepts_explicit_database_url(monkeypatch):
    monkeypatch.setenv("API_KEY", "test-api-key")
    monkeypatch.setenv("DATABASE_URL", "postgresql://postgres@localhost:5432/app")

    settings = Settings()

    assert settings.database_url == "postgresql://postgres@localhost:5432/app"


def test_settings_accepts_explicit_local_database_url(monkeypatch):
    monkeypatch.setenv("API_KEY", "test-api-key")
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql://postgres:password@localhost:5433/app",
    )

    settings = Settings()

    assert settings.database_url == "postgresql://postgres:password@localhost:5433/app"

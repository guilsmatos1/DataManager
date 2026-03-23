from datamanager.core.config import Settings


def test_settings_default():
    settings = Settings()
    assert settings.host == "0.0.0.0"
    assert settings.port == 8686
    assert settings.api_key == ""


def test_is_api_key_configured():
    settings = Settings(api_key="")
    assert settings.is_api_key_configured is False

    settings.api_key = "YOUR_API_KEY_HERE"
    assert settings.is_api_key_configured is False

    settings.api_key = "valid-key"
    assert settings.is_api_key_configured is True

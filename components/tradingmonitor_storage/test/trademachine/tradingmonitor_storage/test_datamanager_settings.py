from unittest.mock import patch

from trademachine.tradingmonitor_storage.api_schemas import DataManagerSettings
from trademachine.tradingmonitor_storage.config import settings
from trademachine.tradingmonitor_storage.db.models import Setting
from trademachine.tradingmonitor_storage.services.datamanager_settings import (
    get_datamanager_settings,
    update_datamanager_settings,
)


def test_get_datamanager_settings_falls_back_to_env_defaults():
    with patch(
        "trademachine.tradingmonitor_storage.services.datamanager_settings.settings"
    ) as mock_settings:
        mock_settings.datamanager_url = settings.datamanager_url
        mock_settings.datamanager_api_key = "YOUR_API_KEY_HERE"
        mock_settings.datamanager_timeout = settings.datamanager_timeout
        resolved = get_datamanager_settings()

    assert resolved.url == settings.datamanager_url
    assert resolved.api_key == "YOUR_API_KEY_HERE"
    assert resolved.api_key_configured is False
    assert resolved.timeout == settings.datamanager_timeout


def test_get_datamanager_settings_prefers_database_values(db_session):
    db_session.add_all(
        [
            Setting(key="datamanager_url", value="http://localhost:9999"),
            Setting(key="datamanager_api_key", value="secret"),
            Setting(key="datamanager_timeout", value="12.5"),
        ]
    )
    db_session.flush()

    with patch(
        "trademachine.tradingmonitor_storage.services.datamanager_settings.settings"
    ) as mock_settings:
        mock_settings.datamanager_url = settings.datamanager_url
        mock_settings.datamanager_api_key = "YOUR_API_KEY_HERE"
        mock_settings.datamanager_timeout = settings.datamanager_timeout
        resolved = get_datamanager_settings(db_session)

    assert resolved.url == "http://localhost:9999"
    assert resolved.api_key == "secret"
    assert resolved.api_key_configured is True
    assert resolved.timeout == 12.5


def test_update_datamanager_settings_persists_values(db_session):
    payload = DataManagerSettings(
        url="http://localhost:8687",
        api_key="updated-key",
        timeout=45.0,
    )

    update_datamanager_settings(db_session, payload)

    rows = {
        row.key: row.value
        for row in db_session.query(Setting)
        .filter(
            Setting.key.in_(
                [
                    "datamanager_url",
                    "datamanager_api_key",
                    "datamanager_timeout",
                ]
            )
        )
        .all()
    }
    assert rows == {
        "datamanager_url": "http://localhost:8687",
        "datamanager_api_key": "updated-key",
        "datamanager_timeout": "45.0",
    }


def test_update_datamanager_settings_preserves_existing_api_key_when_blank(db_session):
    db_session.add(Setting(key="datamanager_api_key", value="existing-key"))
    db_session.flush()

    payload = DataManagerSettings(
        url="http://localhost:8687",
        api_key="",
        timeout=45.0,
    )

    update_datamanager_settings(db_session, payload)

    stored_api_key = (
        db_session.query(Setting).filter(Setting.key == "datamanager_api_key").one()
    )
    assert stored_api_key.value == "existing-key"

from unittest.mock import patch

from trademachine.tradingmonitor_storage.db.models import Setting
from trademachine.tradingmonitor_storage.services.telegram_settings import (
    get_telegram_settings_payload,
)


def test_get_telegram_settings_payload_returns_saved_credentials(db_session):
    expected_bot_token = "123456:ABCdefGhijkLMNop"  # noqa: S105
    expected_chat_id = "2059482856"
    db_session.add_all(
        [
            Setting(
                key="telegram_bot_token",
                value=expected_bot_token,
            ),
            Setting(
                key="telegram_chat_id",
                value=expected_chat_id,
            ),
            Setting(
                key="telegram_notify_closed_trades",
                value="True",
            ),
            Setting(
                key="telegram_notify_system_errors",
                value="False",
            ),
        ]
    )
    db_session.commit()

    with patch(
        "trademachine.tradingmonitor_storage.services.telegram_settings.settings"
    ) as mock_settings:
        mock_settings.telegram_token = None
        mock_settings.telegram_chat_id = None
        payload = get_telegram_settings_payload(db_session)

    assert payload.bot_token == expected_bot_token
    assert payload.chat_id == expected_chat_id
    assert payload.bot_token_configured is True
    assert payload.chat_id_configured is True
    assert payload.bot_token_masked is None
    assert payload.chat_id_masked is None
    assert payload.notify_closed_trades is True
    assert payload.notify_system_errors is False

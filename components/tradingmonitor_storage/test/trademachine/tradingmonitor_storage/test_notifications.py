import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, mock_open, patch

import pytest
from trademachine.tradingmonitor_storage.utils.notifications import NotificationManager


@pytest.fixture
def notification_manager():
    with patch(
        "trademachine.tradingmonitor_storage.utils.notifications.settings"
    ) as mock_settings:
        mock_settings.enable_notifications = True
        mock_settings.telegram_token = "test_token"  # noqa: S105
        mock_settings.telegram_chat_id = "test_chat_id"
        return NotificationManager()


def test_send_document_success(notification_manager):
    async def run_test():
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value.raise_for_status = MagicMock()

            with patch("builtins.open", mock_open(read_data=b"test data")):
                await notification_manager.send_document(
                    "test_path.html", caption="Test Caption"
                )

                assert mock_post.called
                args, kwargs = mock_post.call_args
                assert "bottest_token/sendDocument" in args[0]
                assert kwargs["data"]["chat_id"] == "test_chat_id"
                assert kwargs["data"]["caption"] == "Test Caption"
                assert "document" in kwargs["files"]

    asyncio.run(run_test())


def test_send_document_sync(notification_manager):
    with patch.object(
        notification_manager, "send_document", new_callable=AsyncMock
    ) as mock_send:
        # Mocking asyncio.get_event_loop to avoid issues in test env
        with patch("asyncio.get_event_loop") as mock_loop:
            mock_loop.side_effect = RuntimeError("No loop")
            notification_manager.send_document_sync(
                "test_path.html", caption="Test Sync"
            )
            assert mock_send.called
            # When sync is called, it should trigger asyncio.run(send_document(...))
            # which we can't easily catch the mock inside asyncio.run from outside
            # but if we patch the instance method it should work if it's the same loop or run()


def test_notifications_disabled():
    with patch(
        "trademachine.tradingmonitor_storage.utils.notifications.settings"
    ) as mock_settings:
        mock_settings.enable_notifications = False
        manager = NotificationManager()

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            asyncio.run(manager.send_document("test.html"))
            assert not mock_post.called


def test_notify_trade_closed_uses_db_settings(notification_manager):
    with patch.object(
        notification_manager,
        "_get_runtime_config",
        return_value={
            "token": "db_token",
            "chat_id": "db_chat",
            "notify_closed_trades": True,
            "notify_system_errors": False,
        },
    ):
        with patch.object(notification_manager, "send_message_sync") as mock_send:
            notification_manager.notify_trade_closed(
                strategy_id="123",
                strategy_name="Alpha",
                symbol="EURUSD",
                deal_type="buy",
                ticket=456,
                volume=0.1,
                price=1.23456,
                profit=10.0,
                commission=-0.5,
                swap=0.0,
                timestamp=datetime(2026, 4, 3, 12, 0, 0),
            )

            assert mock_send.called
            kwargs = mock_send.call_args.kwargs
            assert kwargs["token"] == "db_token"  # noqa: S105
            assert kwargs["chat_id"] == "db_chat"
            assert kwargs["enabled"] is True


def test_notify_system_error_respects_toggle(notification_manager):
    with patch.object(
        notification_manager,
        "_get_runtime_config",
        return_value={
            "token": "db_token",
            "chat_id": "db_chat",
            "notify_closed_trades": False,
            "notify_system_errors": False,
        },
    ):
        with patch.object(notification_manager, "send_message_sync") as mock_send:
            notification_manager.notify_system_error(
                context="Ingestion pipeline",
                error="boom",
                topic="DEAL",
            )
            assert not mock_send.called

import asyncio
from unittest.mock import AsyncMock, MagicMock, mock_open, patch

import pytest
from trademachine.tradingmonitor.utils.notifications import NotificationManager


@pytest.fixture
def notification_manager():
    with patch(
        "trademachine.tradingmonitor.utils.notifications.settings"
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
        "trademachine.tradingmonitor.utils.notifications.settings"
    ) as mock_settings:
        mock_settings.enable_notifications = False
        manager = NotificationManager()

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            asyncio.run(manager.send_document("test.html"))
            assert not mock_post.called

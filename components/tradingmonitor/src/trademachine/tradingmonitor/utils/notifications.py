import asyncio
import logging
from datetime import datetime

import httpx
from trademachine.tradingmonitor.config import settings

logger = logging.getLogger("Notifications")


class NotificationManager:
    """Handles sending notifications to external services (e.g., Telegram)."""

    def __init__(self):
        self.enabled = settings.enable_notifications
        self.token = settings.telegram_token
        self.chat_id = settings.telegram_chat_id
        self.api_url = (
            f"https://api.telegram.org/bot{self.token}/sendMessage"
            if self.token
            else None
        )

    async def send_message(self, text: str):
        """Send a generic text message to the configured Telegram chat."""
        if not self.enabled or not self.token or not self.chat_id:
            return

        payload = {"chat_id": self.chat_id, "text": text, "parse_mode": "HTML"}

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(self.api_url, json=payload)
                response.raise_for_status()
        except Exception as e:
            logger.error(f"Failed to send Telegram message: {e}")

    def send_message_sync(self, text: str):
        """Synchronous wrapper for send_message to be used in non-async contexts."""
        if not self.enabled:
            return
        try:
            # Try to get existing loop or create a new one
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # If we are in a thread (like ingestion), we can't easily wait for it.
                # Just spawn a background task if possible or use a separate thread.
                asyncio.run_coroutine_threadsafe(self.send_message(text), loop)
            else:
                loop.run_until_complete(self.send_message(text))
        except RuntimeError:
            # No event loop in this thread, use asyncio.run
            asyncio.run(self.send_message(text))

    def notify_new_strategy(self, strategy_id: str, symbol: str | None = None):
        """Notify when a new strategy is registered."""
        msg = (
            f"🚀 <b>New Strategy Detected</b>\n"
            f"ID: <code>{strategy_id}</code>\n"
            f"Symbol: {symbol or 'Unknown'}\n"
            f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        self.send_message_sync(msg)

    def notify_ingestion_error(self, topic: str, error: str):
        """Notify critical ingestion failures."""
        msg = f"⚠️ <b>Ingestion Error</b>\nTopic: <code>{topic}</code>\nError: <code>{error}</code>"
        self.send_message_sync(msg)

    def notify_low_margin(self, account_id: str, margin: float, threshold: float):
        """Notify when account margin falls below threshold."""
        msg = (
            f"📉 <b>Low Margin Alert</b>\n"
            f"Account: <code>{account_id}</code>\n"
            f"Current Margin: {margin:.2f}\n"
            f"Threshold: {threshold:.2f}%"
        )
        self.send_message_sync(msg)


# Global instance
notifier = NotificationManager()

import asyncio
import html
import logging
from datetime import datetime

import httpx
from trademachine.core.logger import LOGGER_NAME
from trademachine.tradingmonitor_storage.config import settings
from trademachine.tradingmonitor_storage.db.database import SessionLocal
from trademachine.tradingmonitor_storage.db.models import Setting

logger = logging.getLogger(LOGGER_NAME)


class NotificationManager:
    """Handles sending notifications to external services (e.g., Telegram)."""

    def __init__(self):
        self.enabled = settings.enable_notifications
        self.token = settings.telegram_token
        self.chat_id = settings.telegram_chat_id

    @staticmethod
    def _as_bool(value, default: bool = False) -> bool:
        if value is None:
            return default
        return str(value).strip().lower() in {"1", "true", "yes", "on"}

    def _get_runtime_config(self) -> dict[str, object]:
        config: dict[str, object] = {
            "token": self.token,
            "chat_id": self.chat_id,
            "notify_closed_trades": False,
            "notify_system_errors": False,
        }
        try:
            with SessionLocal() as db:
                rows = (
                    db.query(Setting)
                    .filter(
                        Setting.key.in_(
                            [
                                "telegram_bot_token",
                                "telegram_chat_id",
                                "telegram_notify_closed_trades",
                                "telegram_notify_system_errors",
                            ]
                        )
                    )
                    .all()
                )
            values = {row.key: row.value for row in rows}
            config["token"] = self.token or values.get("telegram_bot_token")
            config["chat_id"] = self.chat_id or values.get("telegram_chat_id")
            config["notify_closed_trades"] = self._as_bool(
                values.get("telegram_notify_closed_trades"),
                default=False,
            )
            config["notify_system_errors"] = self._as_bool(
                values.get("telegram_notify_system_errors"),
                default=False,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("Failed to load Telegram settings from DB: %s", exc)
        return config

    async def send_message(
        self,
        text: str,
        *,
        token: str | None = None,
        chat_id: str | None = None,
        enabled: bool | None = None,
    ):
        """Send a generic text message to the configured Telegram chat."""
        token = token or self.token
        chat_id = chat_id or self.chat_id
        if enabled is None:
            enabled = self.enabled
        api_url = f"https://api.telegram.org/bot{token}/sendMessage" if token else None
        if not enabled or not token or not chat_id or not api_url:
            return

        payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(api_url, json=payload)
                response.raise_for_status()
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to send Telegram message: %s", exc)

    async def send_document(
        self,
        file_path: str,
        caption: str | None = None,
        *,
        token: str | None = None,
        chat_id: str | None = None,
        enabled: bool | None = None,
    ):
        """Send a document (file) to the configured Telegram chat."""
        token = token or self.token
        chat_id = chat_id or self.chat_id
        if enabled is None:
            enabled = self.enabled
        if not enabled or not token or not chat_id:
            return

        url = f"https://api.telegram.org/bot{token}/sendDocument"

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                with open(file_path, "rb") as file_handle:
                    files = {"document": file_handle}
                    data = {"chat_id": chat_id}
                    if caption:
                        data["caption"] = caption
                        data["parse_mode"] = "HTML"

                    response = await client.post(url, data=data, files=files)
                    response.raise_for_status()
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to send Telegram document: %s", exc)

    def send_message_sync(
        self,
        text: str,
        *,
        token: str | None = None,
        chat_id: str | None = None,
        enabled: bool | None = None,
    ):
        """Synchronous wrapper for send_message to be used in non-async contexts."""
        if enabled is None:
            enabled = self.enabled
        if not enabled:
            return
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.run_coroutine_threadsafe(
                    self.send_message(
                        text,
                        token=token,
                        chat_id=chat_id,
                        enabled=enabled,
                    ),
                    loop,
                )
            else:
                loop.run_until_complete(
                    self.send_message(
                        text,
                        token=token,
                        chat_id=chat_id,
                        enabled=enabled,
                    )
                )
        except RuntimeError:
            asyncio.run(
                self.send_message(
                    text,
                    token=token,
                    chat_id=chat_id,
                    enabled=enabled,
                )
            )

    def send_document_sync(
        self,
        file_path: str,
        caption: str | None = None,
        *,
        token: str | None = None,
        chat_id: str | None = None,
        enabled: bool | None = None,
    ):
        """Synchronous wrapper for send_document."""
        if enabled is None:
            enabled = self.enabled
        if not enabled:
            return
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.run_coroutine_threadsafe(
                    self.send_document(
                        file_path,
                        caption,
                        token=token,
                        chat_id=chat_id,
                        enabled=enabled,
                    ),
                    loop,
                )
            else:
                loop.run_until_complete(
                    self.send_document(
                        file_path,
                        caption,
                        token=token,
                        chat_id=chat_id,
                        enabled=enabled,
                    )
                )
        except RuntimeError:
            asyncio.run(
                self.send_document(
                    file_path,
                    caption,
                    token=token,
                    chat_id=chat_id,
                    enabled=enabled,
                )
            )

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
        self.notify_system_error(
            context="Ingestion pipeline",
            error=error,
            topic=topic,
        )

    def notify_low_margin(self, account_id: str, margin: float, threshold: float):
        """Notify when account margin falls below threshold."""
        msg = (
            f"📉 <b>Low Margin Alert</b>\n"
            f"Account: <code>{account_id}</code>\n"
            f"Current Margin: {margin:.2f}\n"
            f"Threshold: {threshold:.2f}%"
        )
        self.send_message_sync(msg)

    def notify_trade_closed(
        self,
        *,
        strategy_id: str,
        strategy_name: str | None,
        symbol: str | None,
        deal_type: str,
        ticket: int,
        volume: float,
        price: float,
        profit: float,
        commission: float = 0.0,
        swap: float = 0.0,
        timestamp: datetime,
    ) -> None:
        config = self._get_runtime_config()
        if not config["notify_closed_trades"]:
            return

        net_profit = profit + commission + swap
        safe_name = html.escape(strategy_name or strategy_id)
        safe_symbol = html.escape(symbol or "—")
        safe_type = html.escape(deal_type.upper())
        safe_strategy_id = html.escape(strategy_id)
        msg = (
            "✅ <b>Trade Fechado</b>\n"
            f"Estratégia: <b>{safe_name}</b> <code>#{safe_strategy_id}</code>\n"
            f"Símbolo: <b>{safe_symbol}</b>\n"
            f"Lado: <b>{safe_type}</b>\n"
            f"Ticket: <code>{ticket}</code>\n"
            f"Volume: <b>{volume:.2f}</b>\n"
            f"Preço: <b>{price:.5f}</b>\n"
            f"Profit: <b>{profit:.2f}</b>\n"
            f"Comissão: <b>{commission:.2f}</b>\n"
            f"Swap: <b>{swap:.2f}</b>\n"
            f"Net: <b>{net_profit:.2f}</b>\n"
            f"Fechamento: <code>{timestamp.strftime('%Y-%m-%d %H:%M:%S UTC')}</code>"
        )
        self.send_message_sync(
            msg,
            token=config["token"],
            chat_id=config["chat_id"],
            enabled=True,
        )

    def notify_system_error(
        self,
        *,
        context: str,
        error: str,
        topic: str | None = None,
    ) -> None:
        config = self._get_runtime_config()
        if not config["notify_system_errors"]:
            return

        safe_context = html.escape(context)
        safe_error = html.escape(error[:1500])
        topic_line = f"\nTopic: <code>{html.escape(topic)}</code>" if topic else ""
        msg = (
            "🚨 <b>Erro do Sistema</b>\n"
            f"Contexto: <b>{safe_context}</b>{topic_line}\n"
            f"Erro: <code>{safe_error}</code>"
        )
        self.send_message_sync(
            msg,
            token=config["token"],
            chat_id=config["chat_id"],
            enabled=True,
        )


notifier = NotificationManager()

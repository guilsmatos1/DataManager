from __future__ import annotations

from sqlalchemy.orm import Session
from trademachine.tradingmonitor_storage.api_schemas import TelegramSettings
from trademachine.tradingmonitor_storage.config import settings
from trademachine.tradingmonitor_storage.db.models import Setting
from trademachine.tradingmonitor_storage.services.settings_utils import (
    get_setting_bool,
    get_setting_str,
)


def _set(db: Session, key: str, val: object) -> None:
    s = db.query(Setting).filter(Setting.key == key).first()
    if not s:
        s = Setting(key=key, value=str(val) if val is not None else "")
        db.add(s)
    else:
        s.value = str(val) if val is not None else ""


def _is_real_value(val: str | None) -> bool:
    """Return False for None, empty, or obvious placeholder values."""
    if not val:
        return False
    return val.strip().lower() not in {"your_bot_token_here", "your_chat_id_here", ""}


def get_telegram_settings_payload(db: Session) -> TelegramSettings:
    keys = [
        "telegram_bot_token",
        "telegram_chat_id",
        "var_95_limit",
        "default_initial_balance",
    ]
    rows = db.query(Setting).filter(Setting.key.in_(keys)).all()
    by_key = {row.key: row.value for row in rows}

    real_page_mode = get_setting_str(db, "real_page_mode", default="real")
    if real_page_mode not in {"real", "demo"}:
        real_page_mode = "real"

    env_token = (
        settings.telegram_token if _is_real_value(settings.telegram_token) else None
    )
    env_chat_id = (
        settings.telegram_chat_id if _is_real_value(settings.telegram_chat_id) else None
    )
    bot_token_val = by_key.get("telegram_bot_token")
    chat_id_val = by_key.get("telegram_chat_id")
    var_95_raw = by_key.get("var_95_limit")
    default_ib_raw = by_key.get("default_initial_balance")

    return TelegramSettings(
        bot_token=env_token or bot_token_val,
        chat_id=env_chat_id or chat_id_val,
        bot_token_configured=bool(env_token or bot_token_val),
        chat_id_configured=bool(env_chat_id or chat_id_val),
        notify_closed_trades=get_setting_bool(
            db, "telegram_notify_closed_trades", default=False
        ),
        notify_system_errors=get_setting_bool(
            db, "telegram_notify_system_errors", default=False
        ),
        var_95_threshold=float(var_95_raw) if var_95_raw else None,
        default_initial_balance=float(default_ib_raw) if default_ib_raw else 100_000.0,
        real_page_mode=real_page_mode,
    )


def update_telegram_settings_payload(db: Session, payload: TelegramSettings) -> None:
    if payload.bot_token and payload.bot_token.strip():
        _set(db, "telegram_bot_token", payload.bot_token)
    if payload.chat_id and payload.chat_id.strip():
        _set(db, "telegram_chat_id", payload.chat_id)
    _set(db, "telegram_notify_closed_trades", payload.notify_closed_trades)
    _set(db, "telegram_notify_system_errors", payload.notify_system_errors)
    _set(db, "var_95_limit", payload.var_95_threshold)
    _set(db, "default_initial_balance", payload.default_initial_balance)
    _set(db, "real_page_mode", payload.real_page_mode)
    db.commit()

from __future__ import annotations

from sqlalchemy.orm import Session
from trademachine.tradingmonitor_storage.api_schemas import DataManagerSettings
from trademachine.tradingmonitor_storage.config import settings
from trademachine.tradingmonitor_storage.db.models import Setting


def _is_secret_configured(value: str | None) -> bool:
    if value is None:
        return False
    normalized = value.strip()
    return bool(normalized and normalized.upper() != "YOUR_API_KEY_HERE")


def _get_setting_value(db: Session | None, key: str) -> str | None:
    if db is None:
        return None

    setting = db.query(Setting).filter(Setting.key == key).first()
    if setting is None or setting.value is None:
        return None

    value = setting.value.strip()
    return value or None


def _set_setting_value(db: Session, key: str, value: object) -> None:
    setting = db.query(Setting).filter(Setting.key == key).first()
    serialized = str(value) if value is not None else ""
    if setting is None:
        db.add(Setting(key=key, value=serialized))
        return

    setting.value = serialized


def get_datamanager_settings(db: Session | None = None) -> DataManagerSettings:
    url = _get_setting_value(db, "datamanager_url") or settings.datamanager_url
    api_key = (
        settings.datamanager_api_key
        if _is_secret_configured(settings.datamanager_api_key)
        else (
            _get_setting_value(db, "datamanager_api_key")
            or settings.datamanager_api_key
        )
    )
    timeout_raw = _get_setting_value(db, "datamanager_timeout")

    try:
        timeout = (
            float(timeout_raw)
            if timeout_raw is not None
            else settings.datamanager_timeout
        )
    except ValueError:
        timeout = settings.datamanager_timeout

    return DataManagerSettings(
        url=url,
        api_key=api_key,
        api_key_configured=_is_secret_configured(api_key),
        timeout=timeout,
    )


def update_datamanager_settings(db: Session, payload: DataManagerSettings) -> None:
    _set_setting_value(db, "datamanager_url", payload.url)
    if payload.api_key.strip():
        _set_setting_value(db, "datamanager_api_key", payload.api_key)
    _set_setting_value(db, "datamanager_timeout", payload.timeout)
    db.commit()

from sqlalchemy.orm import Session
from trademachine.tradingmonitor_storage.db.models import Setting


def get_setting_bool(db: Session, key: str, default: bool = False) -> bool:
    setting = db.query(Setting).filter(Setting.key == key).first()
    if not setting or setting.value is None:
        return default
    return str(setting.value).strip().lower() in {"1", "true", "yes", "on"}


def get_setting_str(db: Session, key: str, default: str) -> str:
    setting = db.query(Setting).filter(Setting.key == key).first()
    if not setting or setting.value is None or not str(setting.value).strip():
        return default
    return str(setting.value).strip().lower()

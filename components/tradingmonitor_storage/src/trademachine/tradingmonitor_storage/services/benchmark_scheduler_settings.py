from __future__ import annotations

from sqlalchemy.orm import Session
from trademachine.tradingmonitor_storage.api_schemas import BenchmarkSchedulerSettings
from trademachine.tradingmonitor_storage.db.models import Setting

_KEY_ENABLED = "benchmark_sync_enabled"
_KEY_INTERVAL_HOURS = "benchmark_sync_interval_hours"


def _get(db: Session, key: str) -> str | None:
    row = db.query(Setting).filter(Setting.key == key).first()
    if row is None or row.value is None:
        return None
    return row.value.strip() or None


def _set(db: Session, key: str, value: object) -> None:
    row = db.query(Setting).filter(Setting.key == key).first()
    serialized = str(value) if value is not None else ""
    if row is None:
        db.add(Setting(key=key, value=serialized))
    else:
        row.value = serialized


def get_benchmark_scheduler_settings(db: Session) -> BenchmarkSchedulerSettings:
    enabled_raw = _get(db, _KEY_ENABLED)
    interval_raw = _get(db, _KEY_INTERVAL_HOURS)

    enabled = enabled_raw is not None and enabled_raw.lower() in {"1", "true"}

    try:
        interval_hours = float(interval_raw) if interval_raw is not None else 24.0
    except ValueError:
        interval_hours = 24.0

    return BenchmarkSchedulerSettings(enabled=enabled, interval_hours=interval_hours)


def update_benchmark_scheduler_settings(
    db: Session, payload: BenchmarkSchedulerSettings
) -> None:
    _set(db, _KEY_ENABLED, "true" if payload.enabled else "false")
    _set(db, _KEY_INTERVAL_HOURS, payload.interval_hours)
    db.commit()

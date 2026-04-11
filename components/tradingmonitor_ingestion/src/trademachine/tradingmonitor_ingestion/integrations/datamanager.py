from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session
from trademachine.datamanager.public import DataManagerClient
from trademachine.tradingmonitor_storage.public import (
    get_datamanager_settings,
)


def create_datamanager_client(db: Session | None = None) -> DataManagerClient:
    resolved_settings = get_datamanager_settings(db)
    return DataManagerClient(
        base_url=resolved_settings.url,
        api_key=resolved_settings.api_key,
        timeout=resolved_settings.timeout,
    )


def test_datamanager_connection(db: Session) -> dict[str, Any]:
    client = create_datamanager_client(db)
    databases = client.list_databases()
    return {"ok": True, "databases_count": len(databases)}

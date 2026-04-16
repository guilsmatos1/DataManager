from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session
from trademachine.core.logger import LOGGER_NAME
from trademachine.tradingmonitor_ingestion.public import sync_benchmark_from_datamanager
from trademachine.tradingmonitor_storage.public import Benchmark

logger = logging.getLogger(LOGGER_NAME)


def run_benchmark_auto_sync(db: Session) -> dict[str, Any]:
    """Sync all enabled benchmarks. Returns a summary dict."""
    benchmarks: list[Benchmark] = (
        db.query(Benchmark).filter(Benchmark.enabled.is_(True)).all()
    )
    results: dict[str, Any] = {
        "synced": 0,
        "skipped": 0,
        "failed": 0,
        "errors": [],
    }

    for benchmark in benchmarks:
        try:
            result = sync_benchmark_from_datamanager(db, benchmark)
            db.commit()
            if result.get("status") == "synced":
                results["synced"] += 1
                logger.info("Benchmark auto-sync: synced '%s'.", benchmark.name)
            else:
                results["skipped"] += 1
                logger.info(
                    "Benchmark auto-sync: skipped '%s' (%s).",
                    benchmark.name,
                    result.get("message", ""),
                )
        except Exception as exc:
            db.rollback()
            benchmark.last_error = str(exc)
            db.commit()
            results["failed"] += 1
            results["errors"].append({"name": benchmark.name, "error": str(exc)})
            logger.exception("Benchmark auto-sync: failed for '%s'.", benchmark.name)

    return results

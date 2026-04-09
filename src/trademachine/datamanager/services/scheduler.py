import logging
import uuid
from typing import Any

from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from trademachine.core.logger import LOGGER_NAME
from trademachine.datamanager.infrastructure.database import engine
from trademachine.datamanager.services.manager import DataManager
from trademachine.datamanager.services.series_manager import SeriesManager

logger = logging.getLogger(LOGGER_NAME)


def execute_update_job(source: str, asset: str, timeframe: str) -> None:
    """Global task function for APScheduler so it can be safely pickled to the database."""
    logger.info(f"[Scheduler] Running update: {source}/{asset}/{timeframe}")
    try:
        manager = DataManager()
        manager.update_data(source, asset, timeframe)
    except Exception as e:
        logger.error(f"[Scheduler] Update failed for {source}/{asset}/{timeframe}: {e}")


def execute_update_series_job(
    source: str,
    series_id: str,
    lookback_period: str | None = None,
    frequency: str | None = None,
) -> None:
    """Global task function for scheduled FRED series updates."""
    logger.info(
        "[Scheduler] Running series update: %s/%s (lookback=%s, frequency=%s)",
        source,
        series_id,
        lookback_period,
        frequency,
    )
    try:
        manager = SeriesManager()
        manager.update_series(
            source,
            series_id,
            lookback_period=lookback_period,
            frequency=frequency,
        )
    except Exception as e:
        logger.error(
            "[Scheduler] Series update failed for %s/%s: %s",
            source,
            series_id,
            e,
        )


class SchedulerService:
    """Manages scheduled update jobs for DataManager databases.

    Runs jobs in a background daemon thread via APScheduler.
    Jobs are persisted to TimescaleDB (PostgreSQL) using SQLAlchemyJobStore
    so they survive restarts and crashes natively.
    """

    def __init__(self, manager: Any = None, **kwargs: Any) -> None:
        self._manager = (
            manager  # kept for backward compatibility if instantiated with one
        )

        jobstores = {
            "default": SQLAlchemyJobStore(engine=engine, tablename="apscheduler_jobs")
        }
        self._scheduler = BackgroundScheduler(jobstores=jobstores, daemon=True)

    @staticmethod
    def _build_trigger(
        cron: str | None = None,
        interval_minutes: int | None = None,
    ):
        if not cron and not interval_minutes:
            raise ValueError("Either 'cron' or 'interval_minutes' must be provided.")
        return (
            CronTrigger.from_crontab(cron)
            if cron
            else IntervalTrigger(minutes=interval_minutes)
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the background scheduler. Restores persisted jobs automatically."""
        if not self._scheduler.running:
            self._scheduler.start()
            logger.info("[Scheduler] Started database-backed scheduler.")

    def shutdown(self) -> None:
        """Gracefully stop the scheduler (idempotent)."""
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)
            logger.info("[Scheduler] Stopped.")

    # ------------------------------------------------------------------
    # Job Management
    # ------------------------------------------------------------------

    def add_job(
        self,
        source: str,
        asset: str,
        timeframe: str = "M1",
        cron: str | None = None,
        interval_minutes: int | None = None,
    ) -> dict[str, Any]:
        """Schedule a recurring update_data call for source/asset/timeframe.

        Args:
            source: Data source name (e.g. "DUKASCOPY").
            asset: Asset ticker (e.g. "EURUSD").
            timeframe: Target timeframe (default "M1").
            cron: Cron expression with 5 fields (e.g. "0 */4 * * *").
            interval_minutes: Repeat every N minutes (e.g. 60).

        Returns:
            Job metadata dict with job_id and next_run.

        Raises:
            ValueError: If neither cron nor interval_minutes is provided.
        """
        job_id = str(uuid.uuid4())
        trigger = self._build_trigger(cron=cron, interval_minutes=interval_minutes)

        apsjob = self._scheduler.add_job(
            execute_update_job,
            trigger=trigger,
            args=[source, asset, timeframe],
            id=job_id,
            name=f"{source}/{asset}/{timeframe}",
            replace_existing=True,
        )

        trigger_repr = cron if cron else f"every {interval_minutes}min"
        logger.info(
            f"[Scheduler] Job added/updated: {job_id} ({source}/{asset}/{timeframe}, trigger={trigger_repr})"
        )

        return {
            "job_id": job_id,
            "source": source,
            "asset": asset,
            "timeframe": timeframe,
            "trigger": trigger_repr,
            "cron": cron,
            "interval_minutes": interval_minutes,
            "next_run": str(apsjob.next_run_time),
        }

    def add_series_job(
        self,
        source: str,
        series_id: str,
        lookback_period: str | None = None,
        frequency: str | None = None,
        cron: str | None = None,
        interval_minutes: int | None = None,
    ) -> dict[str, Any]:
        """Schedule a recurring update for a FRED/economic series."""
        job_id = str(uuid.uuid4())
        trigger = self._build_trigger(cron=cron, interval_minutes=interval_minutes)

        apsjob = self._scheduler.add_job(
            execute_update_series_job,
            trigger=trigger,
            args=[source, series_id, lookback_period, frequency],
            id=job_id,
            name=f"{source}/{series_id}/SERIES",
            replace_existing=True,
        )

        trigger_repr = cron if cron else f"every {interval_minutes}min"
        logger.info(
            "[Scheduler] Series job added/updated: %s (%s/%s, trigger=%s)",
            job_id,
            source,
            series_id,
            trigger_repr,
        )

        return {
            "job_id": job_id,
            "source": source,
            "asset": series_id,
            "timeframe": "SERIES",
            "trigger": trigger_repr,
            "cron": cron,
            "interval_minutes": interval_minutes,
            "next_run": str(apsjob.next_run_time),
            "lookback_period": lookback_period,
            "frequency": frequency,
        }

    def list_jobs(self) -> list[dict[str, Any]]:
        """Return metadata for all active scheduled jobs."""
        result = []
        for apsjob in self._scheduler.get_jobs():
            args = apsjob.args or ()
            source, asset, timeframe = "", "", "M1"
            extra: dict[str, Any] = {}
            if apsjob.func is execute_update_series_job:
                if len(args) >= 2:
                    source, asset = args[:2]  # type: ignore[misc]
                timeframe = "SERIES"
                if len(args) >= 3:
                    extra["lookback_period"] = args[2]  # type: ignore[misc]
                if len(args) >= 4:
                    extra["frequency"] = args[3]  # type: ignore[misc]
            elif len(args) == 3:
                source, asset, timeframe = args  # type: ignore[misc]

            trigger_repr = str(apsjob.trigger)

            item = {
                "job_id": apsjob.id,
                "name": apsjob.name,
                "source": source,
                "asset": asset,
                "timeframe": timeframe,
                "trigger": trigger_repr,
                "next_run": str(apsjob.next_run_time),
            }
            item.update(extra)
            result.append(item)
        return result

    def remove_job(self, job_id: str) -> bool:
        """Remove a scheduled job by its ID."""
        try:
            self._scheduler.remove_job(job_id)
            logger.info(f"[Scheduler] Job removed: {job_id}")
            return True
        except Exception:
            return False

import json
import logging
import uuid
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger("DataManager")


class SchedulerService:
    """Manages scheduled update jobs for DataManager databases.

    Runs jobs in a background daemon thread via APScheduler.
    Jobs are persisted to ``persist_path`` (JSON) so they survive restarts.
    """

    def __init__(self, manager, persist_path: Path = None):
        self._manager = manager
        self._scheduler = BackgroundScheduler(daemon=True)
        self._jobs: dict[str, dict] = {}
        self._persist_path = Path(persist_path) if persist_path else Path("metadata/scheduler_jobs.json")

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self):
        """Start the background scheduler and restore any persisted jobs."""
        if not self._scheduler.running:
            self._scheduler.start()
            self._load_persisted_jobs()
            logger.info("[Scheduler] Started.")

    def shutdown(self):
        """Gracefully stop the scheduler (idempotent)."""
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)
            logger.info("[Scheduler] Stopped.")

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    def _save_jobs(self):
        """Persist all current jobs to disk as JSON (atomic write via temp-file swap)."""
        jobs_data = [
            {
                "source": meta["source"],
                "asset": meta["asset"],
                "timeframe": meta["timeframe"],
                "cron": meta.get("cron"),
                "interval_minutes": meta.get("interval_minutes"),
            }
            for meta in self._jobs.values()
        ]
        tmp = self._persist_path.with_suffix(".tmp.json")
        try:
            self._persist_path.parent.mkdir(parents=True, exist_ok=True)
            with open(tmp, "w") as f:
                json.dump(jobs_data, f, indent=2)
            tmp.replace(self._persist_path)  # atomic on the same filesystem
        except Exception as e:
            logger.warning(f"[Scheduler] Failed to save jobs to disk: {e}")
            tmp.unlink(missing_ok=True)

    def _load_persisted_jobs(self):
        """Load and reschedule jobs persisted from a previous run."""
        if not self._persist_path.exists():
            return
        try:
            with open(self._persist_path) as f:
                jobs_data = json.load(f)
        except Exception as e:
            logger.warning(f"[Scheduler] Failed to read persisted jobs: {e}")
            return

        restored = 0
        for job in jobs_data:
            try:
                self.add_job(
                    source=job["source"],
                    asset=job["asset"],
                    timeframe=job.get("timeframe", "M1"),
                    cron=job.get("cron"),
                    interval_minutes=job.get("interval_minutes"),
                )
                restored += 1
            except Exception as e:
                logger.warning(f"[Scheduler] Could not restore job {job}: {e}")

        if restored:
            logger.info(f"[Scheduler] Restored {restored} job(s) from disk.")

    def add_job(
        self,
        source: str,
        asset: str,
        timeframe: str = "M1",
        cron: str = None,
        interval_minutes: int = None,
    ) -> dict:
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
        if not cron and not interval_minutes:
            raise ValueError("Either 'cron' or 'interval_minutes' must be provided.")

        job_id = str(uuid.uuid4())

        def _task():
            logger.info(f"[Scheduler] Running update: {source}/{asset}/{timeframe}")
            try:
                self._manager.update_data(source, asset, timeframe)
            except Exception as e:
                logger.error(f"[Scheduler] Update failed for {source}/{asset}/{timeframe}: {e}")

        trigger = CronTrigger.from_crontab(cron) if cron else IntervalTrigger(minutes=interval_minutes)
        apsjob = self._scheduler.add_job(_task, trigger, id=job_id, name=f"{source}/{asset}/{timeframe}")

        meta = {
            "job_id": job_id,
            "source": source,
            "asset": asset,
            "timeframe": timeframe,
            "trigger": cron if cron else f"every {interval_minutes}min",
            # Stored explicitly for persistence (re-scheduling on restart)
            "cron": cron,
            "interval_minutes": interval_minutes,
            "next_run": str(apsjob.next_run_time),
        }
        self._jobs[job_id] = meta
        self._save_jobs()
        logger.info(f"[Scheduler] Job added: {job_id} ({source}/{asset}/{timeframe}, trigger={meta['trigger']})")
        return meta

    def list_jobs(self) -> list[dict]:
        """Return metadata for all active scheduled jobs."""
        result = []
        for job_id, meta in list(self._jobs.items()):
            apsjob = self._scheduler.get_job(job_id)
            if apsjob:
                entry = dict(meta)
                entry["next_run"] = str(apsjob.next_run_time)
                result.append(entry)
        return result

    def remove_job(self, job_id: str) -> bool:
        """Remove a scheduled job by its ID and update persisted state."""
        if job_id not in self._jobs:
            return False
        try:
            self._scheduler.remove_job(job_id)
        except Exception:
            pass
        del self._jobs[job_id]
        self._save_jobs()
        logger.info(f"[Scheduler] Job removed: {job_id}")
        return True

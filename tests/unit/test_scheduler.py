from unittest.mock import MagicMock, PropertyMock, patch

import pytest

from datamanager.services.scheduler import SchedulerService


@pytest.fixture
def scheduler(tmp_path):
    manager = MagicMock()
    service = SchedulerService(manager)
    yield service
    service.shutdown()


def test_start_shutdown(scheduler):
    with patch.object(scheduler._scheduler, "start") as mock_start:
        with patch.object(type(scheduler._scheduler), "running", new_callable=PropertyMock) as mock_running:
            mock_running.return_value = False
            scheduler.start()
            mock_start.assert_called_once()

    with patch.object(scheduler._scheduler, "shutdown") as mock_shutdown:
        with patch.object(type(scheduler._scheduler), "running", new_callable=PropertyMock) as mock_running:
            mock_running.return_value = True
            scheduler.shutdown()
            mock_shutdown.assert_called_once()


def test_add_job_interval(scheduler):
    with patch.object(scheduler._scheduler, "add_job") as mock_add:
        mock_job = MagicMock()
        mock_job.next_run_time = "tomorrow"
        mock_add.return_value = mock_job

        job_meta = scheduler.add_job("MOCK", "EURUSD", interval_minutes=60)

        assert job_meta["source"] == "MOCK"
        assert job_meta["trigger"] == "every 60min"
        mock_add.assert_called_once()


def test_add_job_cron(scheduler):
    with patch.object(scheduler._scheduler, "add_job") as mock_add:
        mock_job = MagicMock()
        mock_job.next_run_time = "tomorrow"
        mock_add.return_value = mock_job

        job_meta = scheduler.add_job("MOCK", "EURUSD", cron="0 * * * *")

        assert job_meta["trigger"] == "0 * * * *"
        mock_add.assert_called_once()


def test_add_job_requires_trigger(scheduler):
    with pytest.raises(ValueError, match="Either 'cron' or 'interval_minutes'"):
        scheduler.add_job("MOCK", "EURUSD")


def test_list_jobs(scheduler):
    scheduler._jobs = {"job1": {"asset": "EURUSD", "source": "MOCK"}}
    with patch.object(scheduler._scheduler, "get_job") as mock_get:
        mock_aps_job = MagicMock()
        mock_aps_job.next_run_time = "soon"
        mock_get.return_value = mock_aps_job

        jobs = scheduler.list_jobs()
        assert len(jobs) == 1
        assert jobs[0]["asset"] == "EURUSD"


def test_remove_job_success(scheduler):
    scheduler._jobs = {"job1": {"asset": "EURUSD"}}
    with patch.object(scheduler._scheduler, "remove_job") as mock_remove:
        result = scheduler.remove_job("job1")
        assert result is True
        assert "job1" not in scheduler._jobs
        mock_remove.assert_called_once_with("job1")


def test_remove_job_fail(scheduler):
    result = scheduler.remove_job("nonexistent")
    assert result is False

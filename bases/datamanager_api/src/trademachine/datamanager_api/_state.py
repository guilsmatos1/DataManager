"""Shared module-level instances for the DataManager API and dashboard."""

import logging

from trademachine.core.logger import LOGGER_NAME
from trademachine.datamanager.public import (
    ActivityStorageManager,
    DataManager,
    SchedulerService,
    SeriesManager,
)
from trademachine.datamanager_api.task_tracker import tracker

manager = DataManager()
series_manager = SeriesManager()
scheduler = SchedulerService(manager)
activity = ActivityStorageManager()
logger = logging.getLogger(LOGGER_NAME)

__all__ = ["manager", "series_manager", "scheduler", "activity", "logger", "tracker"]

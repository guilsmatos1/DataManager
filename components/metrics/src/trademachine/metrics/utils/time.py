"""Time-related helpers used by formula modules."""

from __future__ import annotations

from datetime import datetime


def years_between(start: datetime, end: datetime) -> float:
    """Fractional years between two datetimes."""
    delta = end - start
    return delta.total_seconds() / (365.25 * 24 * 3600)


def months_between(start: datetime, end: datetime) -> float:
    """Fractional months between two datetimes."""
    return years_between(start, end) * 12


def days_between(start: datetime, end: datetime) -> float:
    """Calendar days (fractional) between two datetimes."""
    delta = end - start
    return delta.total_seconds() / (24 * 3600)

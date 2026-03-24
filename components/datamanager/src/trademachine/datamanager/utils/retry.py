from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any, TypeVar

from trademachine.core.logger import LOGGER_NAME

logger = logging.getLogger(LOGGER_NAME)

F = TypeVar("F", bound=Callable[..., Any])


def with_retry(
    func: Callable[..., Any],
    *args: Any,
    max_attempts: int = 3,
    base_delay: float = 1.0,
    exceptions: tuple[type[Exception], ...] = (Exception,),
    **kwargs: Any,
) -> Any:
    """Calls func(*args, **kwargs) with exponential backoff retry.

    Retries up to max_attempts times on the given exception types.
    Delays: base_delay * 2^attempt → 1s, 2s, 4s by default.
    Re-raises the last exception if all attempts fail.
    """
    for attempt in range(max_attempts):
        try:
            return func(*args, **kwargs)
        except exceptions as e:
            if attempt == max_attempts - 1:
                raise
            delay = base_delay * (2**attempt)
            logger.warning(
                f"Attempt {attempt + 1}/{max_attempts} failed: {e}. Retrying in {delay:.1f}s..."
            )
            time.sleep(delay)

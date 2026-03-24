from __future__ import annotations

import logging
import signal
import time
from collections.abc import Callable
from functools import wraps
from typing import Any, TypeVar

from trademachine.core.logger import LOGGER_NAME

logger = logging.getLogger(LOGGER_NAME)

F = TypeVar("F", bound=Callable[..., Any])


class TimeoutError(Exception):
    """Raised when a function call exceeds its timeout."""


def _timeout_handler(_signum, _frame):
    raise TimeoutError("Function call timed out")


def with_retry(
    func: Callable[..., Any],
    *args: Any,
    max_attempts: int = 3,
    base_delay: float = 1.0,
    timeout_seconds: float | None = None,
    jitter: bool = True,
    exceptions: tuple[type[Exception], ...] = (Exception,),
    **kwargs: Any,
) -> Any:
    """Call func(*args, **kwargs) with exponential backoff + jitter retry.

    Optionally enforce a per-call timeout using SIGALRM (Unix only).
    Jitter is added to the base delay to prevent thundering herd:
        delay = base_delay * 2^attempt * uniform(0.5, 1.5)
    Re-raises the last exception if all attempts fail.
    """
    for attempt in range(max_attempts):
        try:
            if timeout_seconds is not None:

                @wraps(func)
                def timed_fn(*a, **kw):
                    # SIGALRM only works on Unix; fall back to no timeout on Windows
                    if hasattr(signal, "SIGALRM"):
                        signal.signal(signal.SIGALRM, _timeout_handler)
                        signal.alarm(
                            int(timeout_seconds) if timeout_seconds >= 1 else 1
                        )
                    try:
                        return func(*a, **kw)
                    finally:
                        if hasattr(signal, "SIGALRM"):
                            signal.alarm(0)

                result = timed_fn(*args, **kwargs)
            else:
                result = func(*args, **kwargs)
            return result
        except exceptions as e:
            if attempt == max_attempts - 1:
                raise
            delay = base_delay * (2**attempt)
            if jitter:
                import random

                delay *= random.uniform(0.5, 1.5)
            logger.warning(
                f"Attempt {attempt + 1}/{max_attempts} failed: {e}. Retrying in {delay:.1f}s..."
            )
            time.sleep(delay)

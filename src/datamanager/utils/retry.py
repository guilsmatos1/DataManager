import logging
import time

logger = logging.getLogger("DataManager")


def with_retry(func, *args, max_attempts: int = 3, base_delay: float = 1.0, exceptions: tuple = (Exception,), **kwargs):
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
            logger.warning(f"Attempt {attempt + 1}/{max_attempts} failed: {e}. Retrying in {delay:.1f}s...")
            time.sleep(delay)

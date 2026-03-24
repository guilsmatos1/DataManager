import asyncio
import logging

from trademachine.core.logger import LOGGER_NAME

logger = logging.getLogger(LOGGER_NAME)

_queue: asyncio.Queue | None = None
_loop: asyncio.AbstractEventLoop | None = None


def init_bridge(queue: asyncio.Queue, loop: asyncio.AbstractEventLoop):
    global _queue, _loop
    _queue = queue
    _loop = loop


def push_event(topic: str, data: dict):
    """Thread-safe: called from TCP ingestion thread, pushes event to async queue."""
    if _queue is None or _loop is None:
        logger.warning("Bridge not initialized; event dropped: %s", topic)
        return
    try:
        event = {"topic": topic, "data": data}
        _loop.call_soon_threadsafe(_queue.put_nowait, event)
    except Exception as e:
        logger.error(f"Bridge push error: {e}")

"""
Unit tests for src/dashboard/bridge.py

The bridge module holds module-level state (_queue, _loop).  Tests must reset
that state after each run to avoid cross-test contamination.
"""

import asyncio
from unittest.mock import MagicMock, patch

import pytest
import trademachine.trading_monitor_dashboard.bridge as bridge_module
from trademachine.trading_monitor_dashboard.bridge import init_bridge, push_event


@pytest.fixture(autouse=True)
def reset_bridge_state():
    """Reset module-level bridge state before and after every test."""
    bridge_module._queue = None
    bridge_module._loop = None
    yield
    bridge_module._queue = None
    bridge_module._loop = None


# ── init_bridge ───────────────────────────────────────────────────────────────


class TestInitBridge:
    def test_init_bridge_sets_queue_and_loop(self):
        # Arrange
        fake_queue = asyncio.Queue()
        fake_loop = MagicMock(spec=asyncio.AbstractEventLoop)
        # Act
        init_bridge(fake_queue, fake_loop)
        # Assert
        assert bridge_module._queue is fake_queue
        assert bridge_module._loop is fake_loop

    def test_init_bridge_overwrites_previous_state(self):
        # Arrange
        q1, l1 = asyncio.Queue(), MagicMock()
        q2, l2 = asyncio.Queue(), MagicMock()
        init_bridge(q1, l1)
        # Act — re-initialise
        init_bridge(q2, l2)
        # Assert — new references stored
        assert bridge_module._queue is q2
        assert bridge_module._loop is l2


# ── push_event ────────────────────────────────────────────────────────────────


class TestPushEvent:
    def test_push_before_init_logs_warning_and_does_not_raise(self):
        # Arrange — bridge not initialised (state is None)
        with patch.object(bridge_module, "logger") as mock_logger:
            # Act
            push_event("DEAL", {"ticket": 1})
        # Assert — warning logged, no exception raised
        mock_logger.warning.assert_called_once()
        assert "Bridge not initialized" in mock_logger.warning.call_args[0][0]

    def test_push_after_init_calls_call_soon_threadsafe(self):
        # Arrange
        fake_queue = MagicMock(spec=asyncio.Queue)
        fake_loop = MagicMock(spec=asyncio.AbstractEventLoop)
        init_bridge(fake_queue, fake_loop)
        # Act
        push_event("EQUITY", {"balance": 10000.0})
        # Assert — event dispatched to the event loop thread-safely
        fake_loop.call_soon_threadsafe.assert_called_once()
        args = fake_loop.call_soon_threadsafe.call_args[0]
        assert args[0] is fake_queue.put_nowait

    def test_push_wraps_topic_and_data_in_event_dict(self):
        # Arrange
        captured = []
        fake_loop = MagicMock(spec=asyncio.AbstractEventLoop)
        # Capture the payload passed to put_nowait
        fake_loop.call_soon_threadsafe.side_effect = lambda fn, event: captured.append(
            event
        )
        fake_queue = MagicMock(spec=asyncio.Queue)
        init_bridge(fake_queue, fake_loop)
        # Act
        push_event("ACCOUNT", {"login": 99, "balance": 5000.0})
        # Assert
        assert len(captured) == 1
        assert captured[0] == {
            "topic": "ACCOUNT",
            "data": {"login": 99, "balance": 5000.0},
        }

    def test_push_exception_in_call_soon_threadsafe_is_swallowed(self):
        # Bridge must never propagate errors to the ingestion thread
        fake_loop = MagicMock(spec=asyncio.AbstractEventLoop)
        fake_loop.call_soon_threadsafe.side_effect = RuntimeError("loop closed")
        fake_queue = MagicMock(spec=asyncio.Queue)
        init_bridge(fake_queue, fake_loop)
        # Act — must not raise
        push_event("DEAL", {})  # should be caught internally

    def test_multiple_events_are_all_dispatched(self):
        # Arrange
        fake_loop = MagicMock(spec=asyncio.AbstractEventLoop)
        fake_queue = MagicMock(spec=asyncio.Queue)
        init_bridge(fake_queue, fake_loop)
        # Act
        push_event("DEAL", {"ticket": 1})
        push_event("EQUITY", {"balance": 100.0})
        push_event("ACCOUNT", {"login": 1})
        # Assert
        assert fake_loop.call_soon_threadsafe.call_count == 3

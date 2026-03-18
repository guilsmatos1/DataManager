from unittest.mock import MagicMock

import pytest

from datamanager.utils.retry import with_retry


def test_succeeds_on_first_attempt():
    func = MagicMock(return_value="ok")
    result = with_retry(func, "arg1", exceptions=(OSError,))
    assert result == "ok"
    assert func.call_count == 1


def test_retries_then_succeeds():
    func = MagicMock(side_effect=[OSError("timeout"), OSError("timeout"), "ok"])
    result = with_retry(func, max_attempts=3, base_delay=0, exceptions=(OSError,))
    assert result == "ok"
    assert func.call_count == 3


def test_raises_after_max_attempts():
    func = MagicMock(side_effect=OSError("always fails"))
    with pytest.raises(OSError, match="always fails"):
        with_retry(func, max_attempts=3, base_delay=0, exceptions=(OSError,))
    assert func.call_count == 3


def test_does_not_retry_unmatched_exception():
    func = MagicMock(side_effect=ValueError("wrong type"))
    with pytest.raises(ValueError):
        with_retry(func, max_attempts=3, base_delay=0, exceptions=(OSError,))
    assert func.call_count == 1


def test_passes_args_and_kwargs():
    func = MagicMock(return_value=42)
    result = with_retry(func, "a", "b", key="val", exceptions=(OSError,))
    assert result == 42
    func.assert_called_once_with("a", "b", key="val")

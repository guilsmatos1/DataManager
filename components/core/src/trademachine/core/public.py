"""Public API for the core component."""

from trademachine.core.interactive import (
    create_prompt_session,
    interactive_history_path,
    read_interactive_input,
)
from trademachine.core.logger import (
    CONSOLE_HANDLER_NAME,
    FILE_HANDLER_NAME,
    LOGGER_NAME,
    SafeTextStream,
    configure_console_streams,
    setup_logger,
)
from trademachine.core.metrics import (
    compute_equity_curve,
    compute_max_drawdown,
    compute_profit_factor,
    compute_retdd,
    compute_sharpe_ratio,
    compute_win_loss_ratio,
    compute_win_rate,
)

__all__ = [
    "CONSOLE_HANDLER_NAME",
    "FILE_HANDLER_NAME",
    "LOGGER_NAME",
    "SafeTextStream",
    "compute_equity_curve",
    "compute_max_drawdown",
    "compute_profit_factor",
    "compute_retdd",
    "compute_sharpe_ratio",
    "compute_win_loss_ratio",
    "compute_win_rate",
    "configure_console_streams",
    "create_prompt_session",
    "interactive_history_path",
    "read_interactive_input",
    "setup_logger",
]

"""CLI entry point for BacktestEngine."""

from trademachine.backtest_engine_cli.typer_app import app


def main() -> None:
    """Runs the BacktestEngine Typer app."""
    app()


if __name__ == "__main__":
    main()

"""
Main Entry Point
===============
Orchestrates the PortfolioMaster application using Typer.
"""

import logging
import sys

from trademachine.core.logger import LOGGER_NAME
from trademachine.portfolio_master_cli import typer_app
from trademachine.portfoliomaster.public import ValidationError

app = typer_app.app
validate_cli_args = typer_app.validate_cli_args


def main():
    """Main execution flow."""
    # Legacy -i flag compatibility: map to 'interactive' subcommand
    if "-i" in sys.argv:
        sys.argv.remove("-i")
        sys.argv.insert(1, "interactive")
    try:
        app()
    except ValidationError as e:
        logging.getLogger(LOGGER_NAME).error(f"Argument Error: {e}")
        sys.exit(2)
    except Exception as e:
        logging.getLogger(LOGGER_NAME).error(f"Unexpected crash: {e}", exc_info=True)
        sys.exit(2)


if __name__ == "__main__":
    main()

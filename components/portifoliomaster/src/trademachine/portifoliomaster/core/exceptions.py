"""
Exceptions Module
=================
Custom exception hierarchy for the PortfolioMaster system.
"""


class PortfolioMasterError(Exception):
    """Base class for all exceptions in PortfolioMaster."""

    pass


class ValidationError(PortfolioMasterError):
    """Raised when CLI arguments fail validation (e.g. oos_pct > 1)."""

    pass


class ParserError(PortfolioMasterError):
    """Raised when an MT5 HTML report cannot be parsed."""

    pass


class OptimizationError(PortfolioMasterError):
    """Raised when errors occur during the optimization process."""

    pass


class DataError(PortfolioMasterError):
    """Raised when strategies have insufficient or corrupt data."""

    pass

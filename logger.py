import logging
import sys

def setup_logger(name="DataManager"):
    """Configures the global system logger."""
    logger = logging.getLogger(name)
    
    # If the logger already has handlers, don't add them again (prevents duplicates in interactive mode)
    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)
    logger.propagate = False

    # Message format
    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S"
    )

    # Console handler (standard output)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # File handler (with UTF-8 support)
    file_handler = logging.FileHandler("log.log", encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger

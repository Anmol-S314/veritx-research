"""veritx_dse.logger — Structured logging with levels.

Replaces ad-hoc print() calls with proper logging.
"""
import logging
import sys
from pathlib import Path

_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_initialized = False


def get_logger(name: str) -> logging.Logger:
    """Get a named logger. Auto-configures on first call."""
    global _initialized
    if not _initialized:
        logging.basicConfig(
            level=logging.INFO,
            format=_LOG_FORMAT,
            datefmt=_LOG_DATE_FORMAT,
            handlers=[logging.StreamHandler(sys.stderr)],
        )
        _initialized = True
    return logging.getLogger(name)


def setup_file_logging(log_path: Path) -> logging.FileHandler:
    """Add file handler for persistent logs."""
    handler = logging.FileHandler(log_path)
    handler.setFormatter(logging.Formatter(_LOG_FORMAT, _LOG_DATE_FORMAT))
    logging.getLogger().addHandler(handler)
    return handler

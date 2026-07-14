"""
utils/logger.py

Centralized logging configuration.

Provides a single `get_logger` factory so every module in the project emits
logs in a consistent format instead of each module configuring logging
independently.
"""

from __future__ import annotations

import logging
import sys

from config import settings

_CONFIGURED: bool = False


def _configure_root_logger() -> None:
    """
    Configure the root logger exactly once for the whole application.

    Sets up a single stream handler with a consistent format and applies the
    log level defined in the application settings.
    """
    global _CONFIGURED
    if _CONFIGURED:
        return

    handler = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.setLevel(settings.LOG_LEVEL)
    root_logger.addHandler(handler)

    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    """
    Return a configured logger for the given module name.

    Args:
        name: Usually `__name__` of the calling module.

    Returns:
        A `logging.Logger` instance ready to use.
    """
    _configure_root_logger()
    return logging.getLogger(name)

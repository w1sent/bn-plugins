import logging
import tempfile
from pathlib import Path

from core.logging import get_logger, set_log_level


def test_get_logger_returns_logger():
    logger = get_logger("test_plugin")
    assert logger.name == "bn.test_plugin"


def test_get_logger_returns_same_instance():
    logger1 = get_logger("test_same")
    logger2 = get_logger("test_same")
    assert logger1 is logger2


def test_logger_has_file_handler():
    logger = get_logger("test_file_handler")
    has_file_handler = any(
        isinstance(h, logging.FileHandler) for h in logger.handlers
    )
    assert has_file_handler


def test_set_log_level():
    logger = get_logger("test_level")
    set_log_level("test_level", "DEBUG")
    assert logger.level == logging.DEBUG


def test_logger_default_level_is_info():
    logger = get_logger("test_default_level")
    assert logger.level == logging.INFO


def test_logger_does_not_propagate():
    logger = get_logger("test_propagate")
    assert logger.propagate is False

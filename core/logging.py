import logging
import sys
from pathlib import Path

_LOG_DIR = Path.home() / ".binaryninja" / "logs"
_LOG_DIR.mkdir(parents=True, exist_ok=True)

_LEVEL_MAP = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
}


def get_logger(name, level="INFO"):
    logger = logging.getLogger(f"bn.{name}")
    if logger.handlers:
        return logger

    logger.setLevel(_LEVEL_MAP.get(level.upper(), logging.INFO))
    logger.propagate = False

    file_handler = logging.FileHandler(_LOG_DIR / f"{name}.log", encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    )
    logger.addHandler(file_handler)

    return logger


def set_log_level(name, level):
    logger = logging.getLogger(f"bn.{name}")
    logger.setLevel(_LEVEL_MAP.get(level.upper(), logging.INFO))

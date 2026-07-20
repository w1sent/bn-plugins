import logging
from pathlib import Path

from binaryninja import log_debug, log_info, log_warn, log_error

_LOG_DIR = Path.home() / ".binaryninja" / "logs"
_LOG_DIR.mkdir(parents=True, exist_ok=True)

_LEVEL_MAP = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
}

_BN_LOG_FUNCS = {
    logging.DEBUG: log_debug,
    logging.INFO: log_info,
    logging.WARNING: log_warn,
    logging.ERROR: log_error,
    logging.CRITICAL: log_error,
}


class _BNConsoleHandler(logging.Handler):
    def emit(self, record):
        log_func = _BN_LOG_FUNCS.get(record.levelno, log_info)
        log_func(self.format(record), record.name)


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

    console_handler = _BNConsoleHandler()
    console_handler.setLevel(logging.INFO)
    logger.addHandler(console_handler)

    return logger


def set_log_level(name, level):
    logger = logging.getLogger(f"bn.{name}")
    logger.setLevel(_LEVEL_MAP.get(level.upper(), logging.INFO))

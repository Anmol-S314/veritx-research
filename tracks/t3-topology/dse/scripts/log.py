"""Shared logger for DSE pipeline scripts.

Usage:
    from log import get_log
    log = get_log("milestone_b")
    log.info("starting synthesis")
    log.warning("burst_ratio fallback to 1.0")
"""
import logging
import sys

_LOGGERS = {}


def get_log(name: str, level: int = logging.INFO) -> logging.Logger:
    if name in _LOGGERS:
        return _LOGGERS[name]
    log = logging.getLogger(f"dse.{name}")
    log.setLevel(level)
    if not log.handlers:
        h = logging.StreamHandler(sys.stderr)
        h.setFormatter(logging.Formatter(f"%(asctime)s [{name}] %(levelname)s %(message)s", datefmt="%H:%M:%S"))
        log.addHandler(h)
    _LOGGERS[name] = log
    return log

"""Structured logging helpers, called from handlers and services."""

import json
import sys

_LEVELS = {"debug": 10, "info": 20, "warn": 30, "error": 40}


def get_logger(name: str):
    def emit(level: str, msg: str, **fields) -> None:
        if _LEVELS.get(level, 20) < _LEVELS.get("info", 20):
            return
        print(json.dumps({"lvl": level, "mod": name, "msg": msg, **fields}), file=sys.stderr)
    return emit


def log_request_started(logger, path: str) -> None:
    logger("info", "request started", path=path)


def log_request_finished(logger, path: str, ms: float) -> None:
    logger("info", "request finished", path=path, ms=round(ms, 2))


def log_error(logger, path: str, err: str) -> None:
    logger("error", "request failed", path=path, error=err)

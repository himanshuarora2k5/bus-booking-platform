"""Structured (JSON) logging: one JSON object per line, easy for tools to search."""

import json
import logging
import os
import sys
from datetime import UTC, datetime


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        # Extra fields passed as logger.info("...", extra={"fields": {...}})
        payload.update(getattr(record, "fields", {}))
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def setup_logging() -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    level = os.environ.get("LOG_LEVEL", "INFO").upper()

    # Our own logs and the web server's startup/error logs all use the same JSON format.
    for name in ("", "uvicorn", "uvicorn.error"):
        logger = logging.getLogger(name)
        logger.handlers = [handler]
        logger.setLevel(level)
        logger.propagate = name == ""

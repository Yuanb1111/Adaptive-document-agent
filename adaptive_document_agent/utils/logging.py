"""Logging configuration that redacts common secret fields."""

import logging
import os
import re

_SECRET_PATTERN = re.compile(r"(?i)(api[_-]?key|password|secret|token)\s*[=:]\s*[^\s,]+")


class SecretRedactionFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        redacted = _SECRET_PATTERN.sub(r"\1=[REDACTED]", message)
        record.msg = redacted
        record.args = ()
        return True


def configure_logging() -> None:
    handler = logging.StreamHandler()
    handler.addFilter(SecretRedactionFilter())
    logging.basicConfig(
        level=getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=[handler],
        force=True,
    )


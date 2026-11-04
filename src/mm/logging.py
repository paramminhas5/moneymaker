"""Structured JSON logging with secret redaction."""

from __future__ import annotations

import logging
import sys
from collections.abc import MutableMapping
from typing import Any

import structlog

from mm.secrets import known_secret_values

REDACTED = "[REDACTED]"
_SENSITIVE_KEYS = ("secret", "api_key", "apikey", "password", "token", "private_key")


def _redact_value(value: Any, secrets: list[str]) -> Any:
    if isinstance(value, str):
        for s in secrets:
            if s in value:
                value = value.replace(s, REDACTED)
    return value


def redact(_: Any, __: str, event_dict: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    secrets = known_secret_values()
    for key in list(event_dict):
        if any(marker in key.lower() for marker in _SENSITIVE_KEYS):
            event_dict[key] = REDACTED
        else:
            event_dict[key] = _redact_value(event_dict[key], secrets)
    return event_dict


def configure_logging(level: str = "INFO", json: bool = True) -> None:
    logging.basicConfig(stream=sys.stderr, level=level, format="%(message)s")
    renderer = structlog.processors.JSONRenderer() if json else structlog.dev.ConsoleRenderer()
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            redact,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(level)),
    )


def get_logger(name: str = "mm") -> Any:
    return structlog.get_logger(name)

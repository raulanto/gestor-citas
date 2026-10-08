"""Logging configuration, JSON formatter, and PII redaction filter."""

import datetime
import json
import logging
import re
from typing import Any

from agenda.logging import get_request_id

# Regex patterns for PII detection
EMAIL_REGEX = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
# Phone pattern: 10 to 13 digits with optional formatting and +52 prefix, avoiding UUIDs or dates
PHONE_REGEX = re.compile(
    r"(?<![a-zA-Z0-9_-])(?:\+?52[\s.-]*)?(?:\(?\d{2,3}\)?[\s.-]*)?\d{3,4}[\s.-]*\d{4}(?![a-zA-Z0-9_-])"
)
JWT_REGEX = re.compile(r"\beyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b")
AUTH_HEADER_REGEX = re.compile(r"(?:Bearer\s+|X-Manage-Token:\s*)[a-zA-Z0-9_.-]+")

PII_FIELD_NAMES = frozenset(
    {
        "phone",
        "email",
        "full_name",
        "manage_token",
        "password",
        "access",
        "refresh",
        "token",
    }
)


def redact_text(text: str) -> str:
    """Redact sensitive patterns (emails, phones, JWTs, tokens) from a string."""
    if not isinstance(text, str):
        return text

    # Redact JWTs first
    text = JWT_REGEX.sub("[REDACTED_TOKEN]", text)
    # Redact auth headers
    text = AUTH_HEADER_REGEX.sub("[REDACTED_TOKEN]", text)
    # Redact emails
    text = EMAIL_REGEX.sub("[REDACTED_EMAIL]", text)
    # Redact phones
    text = PHONE_REGEX.sub("[REDACTED_PHONE]", text)

    return text


def redact_structure(data: Any) -> Any:
    """Recursively redact dictionary keys and string values."""
    if isinstance(data, dict):
        redacted_dict = {}
        for k, v in data.items():
            if str(k).lower() in PII_FIELD_NAMES:
                redacted_dict[k] = "[REDACTED]"
            else:
                redacted_dict[k] = redact_structure(v)
        return redacted_dict
    elif isinstance(data, (list, tuple)):
        redacted_list = [redact_structure(item) for item in data]
        return tuple(redacted_list) if isinstance(data, tuple) else redacted_list
    elif isinstance(data, str):
        return redact_text(data)
    return data


class PIIRedactionFilter(logging.Filter):
    """Filter that masks sensitive personal identifiable information across all log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        # Redact message string
        if isinstance(record.msg, str):
            record.msg = redact_text(record.msg)

        # Redact args if present
        if record.args:
            if isinstance(record.args, dict):
                record.args = redact_structure(record.args)
            elif isinstance(record.args, tuple):
                record.args = tuple(redact_structure(arg) for arg in record.args)

        # Redact extra fields in __dict__
        for key in list(record.__dict__.keys()):
            if key.lower() in PII_FIELD_NAMES:
                record.__dict__[key] = "[REDACTED]"
            elif key not in (
                "name",
                "msg",
                "args",
                "levelname",
                "levelno",
                "pathname",
                "filename",
                "module",
                "exc_info",
                "exc_text",
                "stack_info",
                "lineno",
                "funcName",
                "created",
                "msecs",
                "relativeCreated",
                "thread",
                "threadName",
                "processName",
                "process",
                "taskName",
            ):
                val = record.__dict__[key]
                record.__dict__[key] = redact_structure(val)

        return True


class JSONFormatter(logging.Formatter):
    """Format log records as single-line JSON objects."""

    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.datetime.fromtimestamp(record.created, datetime.UTC).isoformat()
        req_id = getattr(record, "request_id", None) or get_request_id()

        payload: dict[str, Any] = {
            "ts": ts,
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": req_id,
        }

        # Include custom extra fields
        standard_keys = {
            "name",
            "msg",
            "args",
            "levelname",
            "levelno",
            "pathname",
            "filename",
            "module",
            "exc_info",
            "exc_text",
            "stack_info",
            "lineno",
            "funcName",
            "created",
            "msecs",
            "relativeCreated",
            "thread",
            "threadName",
            "processName",
            "process",
            "taskName",
            "message",
            "request_id",
            "request",
            "response",
            "server",
            "socket",
        }

        for key, val in record.__dict__.items():
            if key not in standard_keys and not key.startswith("_"):
                payload[key] = val

        if record.exc_info and not record.exc_text:
            record.exc_text = self.formatException(record.exc_info)
        if record.exc_text:
            payload["exception"] = redact_text(record.exc_text)

        return json.dumps(payload, ensure_ascii=False, default=str)


def get_logging_config(log_level: str = "INFO") -> dict[str, Any]:
    """Return dictionary configuration for standard logging."""
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "filters": {
            "pii_redaction": {
                "()": "config.logging.PIIRedactionFilter",
            },
        },
        "formatters": {
            "json": {
                "()": "config.logging.JSONFormatter",
            },
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "json",
                "filters": ["pii_redaction"],
            },
        },
        "root": {
            "handlers": ["console"],
            "level": log_level,
            "filters": ["pii_redaction"],
        },
        "loggers": {
            "django": {
                "handlers": ["console"],
                "level": log_level,
                "filters": ["pii_redaction"],
                "propagate": False,
            },
            "django.request": {
                "handlers": ["console"],
                "level": log_level,
                "filters": ["pii_redaction"],
                "propagate": False,
            },
            "django.server": {
                "handlers": ["console"],
                "level": log_level,
                "filters": ["pii_redaction"],
                "propagate": False,
            },
            "agenda": {
                "handlers": ["console"],
                "level": log_level,
                "filters": ["pii_redaction"],
                "propagate": False,
            },
        },
    }

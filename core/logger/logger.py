import os
import sys
import logging
from config import CONFIG
from logging.config import dictConfig

from core.logger.log_handler import LOG_DIRECTORY

# Windows consoles default to cp1252; make stdout UTF-8 so JSON logs with any character never crash.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # pragma: no cover
        pass

# Logging configuration
log_config = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "json": {
            "()": "core.logger.log_handler.JsonFormatter",  # JSON logs for Grafana Loki
        },
    },
    "filters": {
        "context_filter": {
            "()": "core.logger.log_handler.ContextLogFilter"
        }
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "json",
            "stream": "ext://sys.stdout",
            "filters": ["context_filter"]
        },
        "file": {
            "class": "core.logger.log_handler.CustomTimedRotatingFileHandler",
            "formatter": "json",
            "filename": os.path.join(LOG_DIRECTORY, "today.log"),
            "when": "midnight",
            "backupCount": 7,
            "encoding": "utf-8",
            "filters": ["context_filter"]
        },
    },
    "loggers": {
        f"{CONFIG.app_name}": {
            "handlers": ["console", "file"],
            "level": CONFIG.log_level.upper(),
            "propagate": False,
        },
    },
}

# Configure logging
dictConfig(log_config)

# Define a logger
LOG = logging.getLogger(f"{CONFIG.app_name}")

# Test logging
LOG.info(f"{CONFIG.app_name} logger initialized")
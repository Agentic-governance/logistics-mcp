"""Structured Logging Configuration"""
import logging
import sys
import os
from datetime import datetime


class StructuredFormatter(logging.Formatter):
    """JSON-structured log formatter"""

    def format(self, record):
        import json
        log_entry = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "module": record.module,
            "message": record.getMessage(),
        }

        # Add extra fields if present
        if hasattr(record, 'event'):
            log_entry['event'] = record.event
        if hasattr(record, 'elapsed_ms'):
            log_entry['elapsed_ms'] = record.elapsed_ms
        if hasattr(record, 'records'):
            log_entry['records'] = record.records

        if record.exc_info and record.exc_info[0]:
            log_entry['exception'] = {
                'type': record.exc_info[0].__name__,
                'message': str(record.exc_info[1]),
            }

        return json.dumps(log_entry, ensure_ascii=False)


def setup_logging(level: str = "INFO", log_file: str = None):
    """Configure structured logging for the application"""
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Console handler with structured format
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(StructuredFormatter())
    root_logger.addHandler(console_handler)

    # File handler (if specified)
    if log_file:
        os.makedirs(os.path.dirname(log_file) or ".", exist_ok=True)
        from logging.handlers import RotatingFileHandler
        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=10 * 1024 * 1024,  # 10MB
            backupCount=5,
        )
        file_handler.setFormatter(StructuredFormatter())
        root_logger.addHandler(file_handler)

    return root_logger

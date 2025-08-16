# logging_setup.py
import logging
import os
import sys
from typing import Optional
from app.config import config

_DEFAULT_FMT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
_configured = False

def configure_logging(level: Optional[str] = None, fmt: str = _DEFAULT_FMT) -> None:
    """Configure logging once, respecting LOG_LEVEL and overruling prior basicConfig."""
    global _configured
    if _configured:
        return

    level_name = (level or config.log_level).upper()
    level_value = getattr(logging, level_name, logging.INFO)

    # Root logger
    root = logging.getLogger()
    root.setLevel(level_value)

    # Ensure there is at least one stream handler to stdout with our formatter
    if not root.handlers:
        h = logging.StreamHandler(sys.stdout)
        h.setLevel(level_value)
        h.setFormatter(logging.Formatter(fmt))
        root.addHandler(h)
    else:
        # Bring existing handlers up to our level & ensure a formatter
        for h in root.handlers:
            h.setLevel(level_value)
            if not h.formatter:
                h.setFormatter(logging.Formatter(fmt))

    # Keep popular framework loggers in sync (don’t down-suppress debug)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "gunicorn.error", "gunicorn.access", "asyncio"):
        logging.getLogger(name).setLevel(level_value)

    _configured = True

def get_logger(name: Optional[str] = None) -> logging.Logger:
    configure_logging()  # ensures configured on first use
    return logging.getLogger(name or __name__)

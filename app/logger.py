# app/logger.py
import logging
from typing import Optional

_DEFAULT_FMT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"

_configured = False

def configure_logging(level: str = "INFO", fmt: str = _DEFAULT_FMT) -> None:
    """Configure root logging once."""
    global _configured
    if _configured:
        return
    logging.basicConfig(level=getattr(logging, level.upper(), logging.INFO), format=fmt)
    # Quiet some noisy libs if you like:
    logging.getLogger("uvicorn.error").setLevel(logging.INFO)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    _configured = True

def get_logger(name: Optional[str] = None) -> logging.Logger:
    """Return a logger, ensuring logging is configured."""
    configure_logging()
    return logging.getLogger(name or __name__)

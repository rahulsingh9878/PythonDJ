"""
Centralised logging configuration for the DJ App.

Call `setup_logging()` once at application startup (inside the lifespan
handler in main.py).  All other modules then just do:

    import logging
    logger = logging.getLogger(__name__)
"""

import logging
import sys


def setup_logging(level: str = "INFO") -> None:
    """Configure root logger with a consistent format."""
    log_level = getattr(logging, level.upper(), logging.INFO)

    logging.basicConfig(
        level=log_level,
        format="%(asctime)s | %(levelname)-8s | %(name)-30s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[logging.StreamHandler(sys.stdout)],
        force=True,  # Override any handlers set before this call
    )

    # Silence noisy third-party loggers
    logging.getLogger("ytmusicapi").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

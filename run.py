"""
Local development entry point.

Run with:
    python run.py

The server starts on http://0.0.0.0:8045 with hot-reload enabled.
For production use Gunicorn (see render.yaml / README.md).
"""

import uvicorn

from app.core.config import settings

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=True,
        log_level=settings.log_level.lower(),
    )

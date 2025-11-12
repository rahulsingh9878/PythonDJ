#!/bin/bash
# helpful for local dev: use PORT env var if present
PORT=${PORT:-8000}
exec gunicorn -k uvicorn.workers.UvicornWorker app:app --bind 0.0.0.0:$PORT

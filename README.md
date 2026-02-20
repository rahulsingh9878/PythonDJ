# YTMusic -> Lyrics FastAPI


Simple FastAPI app that returns YouTube Music recommendations and fetches lyrics via a RapidAPI Musixmatch wrapper.

## Project Structure
The backend has been refactored into a modular structure:
- `app/`: Main application package
  - `api/`: API endpoints and WebSocket routes
  - `core/`: Configuration and state management
  - `services/`: Business logic (Music service, Connection manager)
  - `utils/`: Helper functions
- `run.py`: Script to run the application locally

## Deploy to Render
1. Create a new Git repository and push these files.
2. Sign in to Render and create a new **Web Service**.
- Connect your GitHub repo
- Runtime: Python 3 (Render auto-detects)
- Build Command: `pip install -r requirements.txt`
- Start Command: `gunicorn -k uvicorn.workers.UvicornWorker app.main:app --bind 0.0.0.0:$PORT`
3. Add environment variables in the Render Dashboard:
- `RAPIDAPI_KEY` = your RapidAPI key
- `RAPIDAPI_HOST` = `spotify-web-api3.p.rapidapi.com` (optional)
4. Deploy — once running, visit `https://<your-service>.onrender.com/docs` for Swagger UI.


## Local development
1. Copy `.env.example` to `.env` and fill values.
2. Install deps: `pip install -r requirements.txt`
3. Run locally:
   ```bash
   python run.py
   # OR
   uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
   ```


## Notes
- Keep `RAPIDAPI_KEY` secret. Do not commit it.
- YTMusic first-run may download headers; allow few seconds.

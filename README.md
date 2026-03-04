# Premium Video DJ - Backend

A powerful, modular FastAPI application that powers the **Premium Video DJ** experience. It provides real-time YouTube Music search, smart recommendations, automated radio playlists, and cross-device synchronization.

## 🚀 Key Features

- **Modular FastAPI Architecture**: Refactored into a clean, scalable structure (`api`, `core`, `services`, `utils`).
- **Smart Search & Suggestions**: Real-time search suggestions and dual-category results (Official Songs & Videos).
- **Refined Radio Mode**: Generates seamless playlists based on any track, optimized for "Official Music Video" content to ensure a premium visual experience.
- **Dynamic Recommendations**: Custom Indian-music-focused recommender system that builds a data-driven background cache for faster discovery.
- **WebSocket Sync Client**: Complete crossfade-ready synchronization. One device acts as the player, others as controllers (QR-code based pairing).
- **Lyrics Integration**: Multi-source lyrics engine (YouTube Music + Musixmatch fallback via RapidAPI).
- **Trending Charts**: Direct access to top charts and trending tracks (optimized for the IN region).

## 📂 Project Structure

- `app/`: Main application package
  - `api/`: REST endpoints and WebSocket protocols (`DJSyncClient`).
  - `core/`: Config management (Pydantic based) and global state.
  - `services/`: Core logic (YTMusic integration, Radio engine, Recommender).
  - `utils/`: Processing helpers and text parsers.
- `templates/`: Jinja2 templates (including the unified `index.html`).
- `run.py`: Entry point for local development.

## 🛠️ Local Development

1. **Setup Environment**:
   - Copy `.env.example` to `.env`
   - Set `RAPIDAPI_KEY` for lyrics support.

2. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Run the Server**:
   ```bash
   python run.py
   ```
   *The server defaults to port `8045`.*

4. **Production / Docker**:
   ```bash
   uvicorn app.main:app --host 0.0.0.0 --port 8000
   ```

## ☁️ Deployment (Render)

1. Connect your repository to **Render** as a **Web Service**.
2. **Build Command**: `pip install -r requirements.txt`
3. **Start Command**: `gunicorn -k uvicorn.workers.UvicornWorker app.main:app --bind 0.0.0.0:$PORT`
4. Add Environment Variables for `RAPIDAPI_KEY` and `RAPIDAPI_HOST`.

## 📜 Notes

- **Initial Load**: The first run might take a few seconds as it initializes headers and builds the recommendation database.
- **WebSocket**: Controls are broadcasted globally to all connected clients under the same host for instant synchronization.
- **Radio Mode**: Always prioritizes high-quality official music videos when available.


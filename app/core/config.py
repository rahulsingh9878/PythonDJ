import os

# API Keys and Hosts
RAPIDAPI_KEY = os.environ.get("RAPIDAPI_KEY")
RAPIDAPI_HOST = os.environ.get("RAPIDAPI_HOST", "spotify-web-api3.p.rapidapi.com")
RAPIDAPI_URL = f"https://{RAPIDAPI_HOST}/v1/social/spotify/musixmatchsearchlyrics"

# CORS Origins
ORIGINS = [
    "https://rahulsingh9878.github.io",
    "http://localhost",
    "http://127.0.0.1",
    "http://0.0.0.0:5500",
    "http://localhost:5500"
]

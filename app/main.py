from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .api import endpoints, websocket_routes
from .core.config import ORIGINS

app = FastAPI(title="YTMusic -> Lyrics FastAPI", version="2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(endpoints.router)
app.include_router(websocket_routes.router)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

"""
SecureVoice — FastAPI entrypoint.
Loads .env automatically if python-dotenv is installed.
Run: uvicorn backend.main:app --reload --port 8000
"""
import os
try:
    from dotenv import load_dotenv
    load_dotenv()          # reads .env from project root
except ImportError:
    pass                   # dotenv optional — env vars can be set manually

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pathlib import Path

import logging
logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(name)s  %(message)s")

from .api.routes                import router
from .websockets.stream_handler import ws_router
from .middleware.security       import SecurityHeadersMiddleware, RateLimitMiddleware, setup_cors

app = FastAPI(title="SecureVoice", version="1.0.0", docs_url=None, redoc_url=None)

@app.on_event("startup")
async def _startup():
    from .core.storage import USE_CLOUD, CLOUDINARY_URL
    logger = logging.getLogger("securevoice.startup")
    if USE_CLOUD:
        try:
            import cloudinary
            cloudinary.config(cloudinary_url=CLOUDINARY_URL)
            # Ping the API to catch wrong credentials immediately
            from cloudinary.api import ping
            import asyncio
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(None, ping)
            logger.info("Cloudinary connected: %s", result.get("status"))
        except Exception as e:
            logger.error("Cloudinary connection FAILED: %s", e)
            logger.error("Check CLOUDINARY_URL in your .env — audio uploads will fail.")
    else:
        logger.info("Storage mode: local /uploads folder (set CLOUDINARY_URL for cloud)")

setup_cors(app)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RateLimitMiddleware)

app.include_router(router)
app.include_router(ws_router)

FRONTEND = Path(__file__).parent.parent / "frontend"
app.mount("/static", StaticFiles(directory=str(FRONTEND)), name="static")

@app.get("/listen/{token_id}")
async def listen_page(token_id: str):
    return FileResponse(str(FRONTEND / "index.html"))

@app.get("/expired")
async def expired_page():
    return FileResponse(str(FRONTEND / "pages" / "expired.html"))

@app.get("/admin")
async def admin_page():
    return FileResponse(str(FRONTEND / "pages" / "admin.html"))

@app.get("/")
async def root():
    return FileResponse(str(FRONTEND / "index.html"))

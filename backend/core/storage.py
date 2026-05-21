"""
Cloud storage adapter — Cloudinary.

If CLOUDINARY_URL is set in the environment, audio is uploaded to Cloudinary
and streamed from there. Otherwise falls back to local /uploads directory
(for local dev without a Cloudinary account).

Cloudinary free tier: 25 GB storage + 25 GB bandwidth/month.
Sign up at https://cloudinary.com — the CLOUDINARY_URL is on your dashboard.
"""

import os
import io
import time
import asyncio
import httpx
from pathlib import Path

# ── Detect mode ────────────────────────────────────────────────────────────────
CLOUDINARY_URL = os.getenv("CLOUDINARY_URL", "").strip()
USE_CLOUD      = bool(CLOUDINARY_URL)

UPLOADS_DIR = Path(__file__).parent.parent.parent / "uploads"
UPLOADS_DIR.mkdir(exist_ok=True)

CHUNK_SIZE = 16 * 1024   # 16 KB

# ── Lazy Cloudinary init ───────────────────────────────────────────────────────
_cloudinary_ready = False

def _init_cloudinary():
    global _cloudinary_ready
    if _cloudinary_ready:
        return
    import cloudinary
    cloudinary.config(cloudinary_url=CLOUDINARY_URL)
    _cloudinary_ready = True


# ══════════════════════════════════════════════════════════════════════════════
#  UPLOAD
# ══════════════════════════════════════════════════════════════════════════════

async def upload_audio(data: bytes, filename: str) -> str:
    """
    Upload audio bytes.
    Returns a storage key (local filename OR Cloudinary public_id).
    The same key is stored in the token record and passed back to stream_audio().
    """
    if USE_CLOUD:
        return await _upload_to_cloudinary(data, filename)
    return _save_local(data, filename)


def _save_local(data: bytes, filename: str) -> str:
    (UPLOADS_DIR / filename).write_bytes(data)
    return filename


async def _upload_to_cloudinary(data: bytes, filename: str) -> str:
    _init_cloudinary()
    import cloudinary.uploader

    stem = Path(filename).stem  # hex token, no extension

    loop = asyncio.get_running_loop()   # py3.10-safe (not deprecated get_event_loop)
    result = await loop.run_in_executor(
        None,
        lambda: cloudinary.uploader.upload(
            io.BytesIO(data),
            public_id=f"securevoice/{stem}",
            resource_type="video",    # Cloudinary calls audio "video"
            overwrite=False,
            # Use "upload" type (not "authenticated") — free tier compatible.
            # Security comes from the unguessable public_id + one-time token system,
            # NOT from Cloudinary access control.
            type="upload",
        )
    )
    return result["public_id"]   # e.g. "securevoice/a3f9bc1d..."


# ══════════════════════════════════════════════════════════════════════════════
#  STREAM  (async generator of raw bytes chunks)
# ══════════════════════════════════════════════════════════════════════════════

async def stream_audio_bytes(storage_key: str):
    """
    Async generator that yields raw audio bytes in CHUNK_SIZE pieces.
    Abstracts over local file vs Cloudinary.
    """
    if USE_CLOUD and storage_key.startswith("securevoice/"):
        async for chunk in _stream_from_cloudinary(storage_key):
            yield chunk
    else:
        async for chunk in _stream_local(storage_key):
            yield chunk


async def _stream_local(filename: str):
    path = UPLOADS_DIR / filename
    if not path.exists():
        raise FileNotFoundError(f"Audio not found locally: {filename}")
    with open(path, "rb") as f:
        while True:
            raw = f.read(CHUNK_SIZE)
            if not raw:
                break
            yield raw
            await asyncio.sleep(0)


async def _stream_from_cloudinary(public_id: str):
    _init_cloudinary()
    from cloudinary.utils import cloudinary_url

    # Plain delivery URL — no signed auth needed for "upload" type assets.
    url, _ = cloudinary_url(
        public_id,
        resource_type="video",
        type="upload",
        secure=True,
    )

    if not url:
        raise RuntimeError(f"Cloudinary could not build URL for: {public_id}")

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            async with client.stream("GET", url) as response:
                if response.status_code == 404:
                    raise FileNotFoundError(f"Audio not found on Cloudinary: {public_id}")
                response.raise_for_status()
                async for chunk in response.aiter_bytes(CHUNK_SIZE):
                    yield chunk
    except httpx.HTTPStatusError as e:
        raise RuntimeError(f"Cloudinary delivery error {e.response.status_code}: {public_id}") from e
    except httpx.TimeoutException:
        raise RuntimeError("Cloudinary stream timed out — try again.") from None
    except httpx.RequestError as e:
        raise RuntimeError(f"Network error reaching Cloudinary: {e}") from e


# ══════════════════════════════════════════════════════════════════════════════
#  SIZE HELPER  (for progress bar)
# ══════════════════════════════════════════════════════════════════════════════

async def get_audio_size(storage_key: str) -> int:
    """Return file size in bytes, or 0 if unknown."""
    if USE_CLOUD and storage_key.startswith("securevoice/"):
        return await _cloudinary_size(storage_key)
    path = UPLOADS_DIR / storage_key
    return path.stat().st_size if path.exists() else 0


async def _cloudinary_size(public_id: str) -> int:
    _init_cloudinary()
    from cloudinary.api import resource as cl_resource

    loop = asyncio.get_running_loop()
    try:
        info = await loop.run_in_executor(
            None,
            lambda: cl_resource(public_id, resource_type="video")
        )
        return int(info.get("bytes", 0))
    except Exception:
        return 0   # non-fatal — progress bar just won't show

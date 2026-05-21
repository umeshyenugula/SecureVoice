"""
REST API routes — all token/session calls are now async (MongoDB-compatible).
"""
import math
import time
import os
from fastapi import APIRouter, HTTPException, UploadFile, File, Request
from fastapi.responses import JSONResponse
from pathlib import Path

from ..core.storage import upload_audio, USE_CLOUD
from ..core.tokens import (
    create_token, get_token, is_token_valid, expire_token,
    create_session, get_session, mark_session_started, destroy_session,
)
from ..models.schemas import (
    CreateTokenRequest, TokenResponse,
    VerifyFaceRequest, VerifyFaceResponse,
    PlaybackStartRequest, PlaybackDoneRequest,
)

router = APIRouter(prefix="/api")

UPLOADS_DIR = Path(__file__).parent.parent.parent / "uploads"
UPLOADS_DIR.mkdir(exist_ok=True)

FACE_THRESHOLD = float(os.getenv("FACE_THRESHOLD", "0.40"))
MAX_UPLOAD_MB  = int(os.getenv("MAX_UPLOAD_MB", "50"))

# -- Per-token failed attempt tracking (brute-force lockout) --
_failed_attempts: dict = {}
MAX_FACE_ATTEMPTS = 5   # invalidate token after this many failed face checks


def _euclidean_distance(a: list, b: list) -> float:
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


# ── Upload audio ───────────────────────────────────────────────────────────────

@router.post("/admin/upload-audio")
async def upload_audio_route(file: UploadFile = File(...)):
    allowed = {".mp3", ".wav", ".ogg", ".m4a", ".aac"}
    suffix  = Path(file.filename).suffix.lower()
    if suffix not in allowed:
        raise HTTPException(400, "Unsupported audio format.")

    import secrets
    safe_name = secrets.token_hex(16) + suffix

    data = await file.read()
    if len(data) > MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(413, f"File too large (max {MAX_UPLOAD_MB} MB).")

    # storage_key is a local filename (dev) or Cloudinary public_id (prod)
    storage_key = await upload_audio(data, safe_name)
    return {"filename": storage_key, "cloud": USE_CLOUD}


# ── Create token ───────────────────────────────────────────────────────────────

@router.post("/admin/create-token", response_model=TokenResponse)
async def admin_create_token(req: CreateTokenRequest, request: Request):
    # For local mode, verify the file exists before creating token
    if not USE_CLOUD:
        audio_path = UPLOADS_DIR / req.audio_filename
        if not audio_path.exists():
            raise HTTPException(404, "Audio file not found. Upload it first.")

    ip_lock  = req.ip_lock or str(request.client.host)
    token_id = await create_token(req.audio_filename, req.face_embedding, ip_lock)

    base_url = str(request.base_url).rstrip("/")
    return TokenResponse(token_id=token_id, url=f"{base_url}/listen/{token_id}")


# ── Token status ───────────────────────────────────────────────────────────────

@router.get("/token/{token_id}/status")
async def token_status(token_id: str):
    token = await get_token(token_id)
    if token is None:
        raise HTTPException(404, "Token not found.")
    return {"valid": not token["used"], "created_at": token["created_at"]}


# ── Face verification ──────────────────────────────────────────────────────────

@router.post("/verify-face", response_model=VerifyFaceResponse)
async def verify_face(req: VerifyFaceRequest):
    token = await get_token(req.token_id)
    if token is None or token["used"]:
        raise HTTPException(403, "Token is invalid or has been used.")

    # Brute-force lockout: burn the token after too many failed attempts
    attempts = _failed_attempts.get(req.token_id, 0)
    if attempts >= MAX_FACE_ATTEMPTS:
        await expire_token(req.token_id)          # permanently invalidate
        _failed_attempts.pop(req.token_id, None)
        raise HTTPException(403, "Too many failed attempts. Token revoked.")

    ref  = token["face_embedding"]
    live = req.face_descriptor

    if len(ref) != len(live):
        raise HTTPException(400, "Embedding dimension mismatch.")

    distance = _euclidean_distance(ref, live)
    # Correct similarity: clamp normalised inverse of euclidean distance.
    # Max meaningful distance for face-api 128-D embeddings is ~1.0.
    similarity = max(0.0, round(1.0 - min(distance, 1.0), 3))
    verified   = distance < FACE_THRESHOLD

    if not verified:
        _failed_attempts[req.token_id] = attempts + 1
        return VerifyFaceResponse(
            verified=False, similarity=similarity,
            message="Face verification failed. This message is not for you.",
        )

    # Success — clear any prior failed attempts
    _failed_attempts.pop(req.token_id, None)

    session = await create_session(req.token_id)
    session["audio_file"] = token["audio_file"]

    return VerifyFaceResponse(
        verified=True, similarity=similarity,
        session_id=session["session_id"], key_b64=session["key_b64"],
        message="Identity confirmed.",
    )


# ── Playback lifecycle ─────────────────────────────────────────────────────────

@router.post("/playback/start")
async def playback_start(req: PlaybackStartRequest):
    session = await get_session(req.session_id)
    if session is None:
        raise HTTPException(403, "Session invalid or expired.")
    if session["started"]:
        raise HTTPException(403, "Playback already started. Anti-replay triggered.")

    await mark_session_started(req.session_id)
    await expire_token(session["token_id"])
    return {"ok": True, "message": "Token expired. Streaming authorised."}


@router.post("/playback/done")
async def playback_done(req: PlaybackDoneRequest):
    await destroy_session(req.session_id)
    return {"ok": True, "message": "Session destroyed."}

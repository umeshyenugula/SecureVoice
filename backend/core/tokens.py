"""
Token management — MongoDB-backed (motor async driver).
Falls back to in-memory if MONGO_URI is not set (for local dev without MongoDB).
"""
import os
import secrets
import time
from typing import Optional
from .encryption import generate_session_key, key_to_b64

# ── Config from env ────────────────────────────────────────────────────────────
MONGO_URI    = os.getenv("MONGO_URI", "")
MONGO_DB     = os.getenv("MONGO_DB_NAME", "securevoice")
USE_MONGO    = bool(MONGO_URI)

RATE_LIMIT_WINDOW = 60
RATE_LIMIT_MAX    = 10

# ── In-memory fallback (dev only) ──────────────────────────────────────────────
_tokens:      dict[str, dict] = {}
_sessions:    dict[str, dict] = {}
_ip_attempts: dict[str, list] = {}

# ── MongoDB client (lazy init) ─────────────────────────────────────────────────
_mongo_client = None
_db           = None


def _get_db():
    global _mongo_client, _db
    if _db is None:
        import motor.motor_asyncio
        _mongo_client = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URI)
        _db = _mongo_client[MONGO_DB]
    return _db


# ══════════════════════════════════════════════════════════════════════════════
#  TOKEN OPERATIONS
# ══════════════════════════════════════════════════════════════════════════════

async def create_token(audio_file: str, face_embedding: list, ip_lock: str = None) -> str:
    token_id = secrets.token_urlsafe(12)
    record = {
        "token_id":       token_id,
        "audio_file":     audio_file,
        "face_embedding": face_embedding,
        "created_at":     time.time(),
        "used":           False,
        "used_at":        None,
        "ip_lock":        ip_lock,
    }
    if USE_MONGO:
        db = _get_db()
        await db["tokens"].insert_one(record)
    else:
        _tokens[token_id] = record
    return token_id


async def get_token(token_id: str) -> Optional[dict]:
    if USE_MONGO:
        db = _get_db()
        doc = await db["tokens"].find_one({"token_id": token_id}, {"_id": 0})
        return doc
    return _tokens.get(token_id)


async def is_token_valid(token_id: str) -> bool:
    rec = await get_token(token_id)
    if rec is None:
        return False
    return not rec["used"]


async def expire_token(token_id: str):
    now = time.time()
    if USE_MONGO:
        db = _get_db()
        await db["tokens"].update_one(
            {"token_id": token_id},
            {"$set": {"used": True, "used_at": now}}
        )
    else:
        if token_id in _tokens:
            _tokens[token_id]["used"]    = True
            _tokens[token_id]["used_at"] = now


# ══════════════════════════════════════════════════════════════════════════════
#  SESSION OPERATIONS
# ══════════════════════════════════════════════════════════════════════════════

async def create_session(token_id: str) -> dict:
    session_id = secrets.token_urlsafe(24)
    key        = generate_session_key()
    record = {
        "session_id": session_id,
        "token_id":   token_id,
        "key_b64":    key_to_b64(key),
        "created_at": time.time(),
        "started":    False,
        "finished":   False,
        "expires_at": time.time() + 3600,
    }
    if USE_MONGO:
        db = _get_db()
        await db["sessions"].insert_one(record)
        # TTL index — MongoDB auto-deletes expired sessions
        await db["sessions"].create_index("expires_at", expireAfterSeconds=0)
    else:
        _sessions[session_id] = record
    return record


async def get_session(session_id: str) -> Optional[dict]:
    if USE_MONGO:
        db  = _get_db()
        doc = await db["sessions"].find_one({"session_id": session_id}, {"_id": 0})
        if doc and time.time() > doc["expires_at"]:
            await db["sessions"].delete_one({"session_id": session_id})
            return None
        return doc
    rec = _sessions.get(session_id)
    if rec and time.time() > rec["expires_at"]:
        del _sessions[session_id]
        return None
    return rec


async def mark_session_started(session_id: str):
    if USE_MONGO:
        db = _get_db()
        await db["sessions"].update_one(
            {"session_id": session_id},
            {"$set": {"started": True}}
        )
    else:
        if session_id in _sessions:
            _sessions[session_id]["started"] = True


async def destroy_session(session_id: str):
    if USE_MONGO:
        db = _get_db()
        await db["sessions"].delete_one({"session_id": session_id})
    else:
        _sessions.pop(session_id, None)


# ══════════════════════════════════════════════════════════════════════════════
#  RATE LIMITING  (always in-memory — fast, no DB round-trip needed)
# ══════════════════════════════════════════════════════════════════════════════

def check_rate_limit(ip: str) -> bool:
    now      = time.time()
    attempts = _ip_attempts.get(ip, [])
    attempts = [t for t in attempts if now - t < RATE_LIMIT_WINDOW]
    if len(attempts) >= RATE_LIMIT_MAX:
        _ip_attempts[ip] = attempts
        return False
    attempts.append(now)
    _ip_attempts[ip] = attempts
    return True

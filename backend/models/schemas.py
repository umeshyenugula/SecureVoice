"""
Pydantic models + MongoDB collection helpers.
For production, set MONGO_URI env var and use motor (async MongoDB driver).
In dev/demo mode, falls back to the in-memory store in core/tokens.py.
"""
from __future__ import annotations
from typing import Optional, List
from pydantic import BaseModel, Field
import time


# ── Request / Response Schemas ─────────────────────────────────────────────────

class CreateTokenRequest(BaseModel):
    audio_filename: str          # filename that was uploaded to /uploads
    face_embedding: List[float]  # 128-d face descriptor array
    ip_lock: Optional[str] = None


class TokenResponse(BaseModel):
    token_id: str
    url: str


class VerifyFaceRequest(BaseModel):
    token_id: str
    face_descriptor: List[float]  # live face embedding from client


class VerifyFaceResponse(BaseModel):
    verified: bool
    similarity: float
    session_id: Optional[str] = None
    key_b64: Optional[str] = None
    message: str


class SessionStatusResponse(BaseModel):
    valid: bool
    started: bool
    finished: bool


class PlaybackStartRequest(BaseModel):
    session_id: str


class PlaybackDoneRequest(BaseModel):
    session_id: str


# ── MongoDB helpers (async, using motor) ───────────────────────────────────────
# Uncomment and configure if you want persistent storage with MongoDB.

# import motor.motor_asyncio
# import os
#
# MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
# _client   = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URI)
# _db       = _client["securevoice"]
#
# tokens_col   = _db["tokens"]
# sessions_col = _db["sessions"]
#
# async def save_token(record: dict):
#     await tokens_col.insert_one(record)
#
# async def fetch_token(token_id: str) -> dict | None:
#     return await tokens_col.find_one({"token_id": token_id}, {"_id": 0})
#
# async def expire_token_db(token_id: str):
#     await tokens_col.update_one(
#         {"token_id": token_id},
#         {"$set": {"used": True, "used_at": time.time()}}
#     )

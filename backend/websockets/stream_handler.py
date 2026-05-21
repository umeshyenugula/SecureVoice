"""
WebSocket streaming handler — async token/session calls.
"""
import json
import logging
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from ..core.tokens    import get_session, get_token, destroy_session
from ..core.streaming import stream_encrypted_audio

logger    = logging.getLogger(__name__)
ws_router = APIRouter()


async def _send_error(ws: WebSocket, code: str, message: str):
    try:
        await ws.send_text(json.dumps({"error": code, "message": message}))
    except Exception:
        pass


@ws_router.websocket("/ws/stream/{session_id}")
async def websocket_stream(websocket: WebSocket, session_id: str):
    await websocket.accept()

    # ── Validate session ───────────────────────────────────────────────────────
    session = await get_session(session_id)
    if session is None:
        await _send_error(websocket, "invalid_session", "Session does not exist or has expired.")
        await websocket.close(code=4001)
        return

    if not session.get("started"):
        await _send_error(websocket, "not_started", "Playback not authorised yet.")
        await websocket.close(code=4002)
        return

    # ── Attach audio_file from token onto the session dict ────────────────────
    # (session record in DB does not store audio_file; token does)
    token = await get_token(session["token_id"])
    if token is None:
        await _send_error(websocket, "token_gone", "Token record missing.")
        await websocket.close(code=4003)
        return

    # Mutate the local session dict — this is what stream_encrypted_audio reads
    session["audio_file"] = token["audio_file"]

    # ── Stream ─────────────────────────────────────────────────────────────────
    try:
        async for chunk_json in stream_encrypted_audio(session):
            await websocket.send_text(chunk_json)

    except FileNotFoundError as e:
        logger.error("Audio file missing: %s", e)
        await _send_error(websocket, "audio_missing",
                          "Audio file could not be found. Contact the sender.")

    except WebSocketDisconnect:
        logger.info("Client disconnected mid-stream (session %s)", session_id)

    except RuntimeError as e:
        # Raised by storage adapter for Cloudinary errors with a human-readable message
        logger.error("Stream RuntimeError (session %s): %s", session_id, e)
        await _send_error(websocket, "stream_error", str(e))

    except Exception as e:
        logger.exception("Unexpected stream error (session %s)", session_id)
        await _send_error(websocket, "stream_error",
                          f"Unexpected error: {type(e).__name__}: {e}")

    finally:
        await destroy_session(session_id)
        try:
            await websocket.close()
        except Exception:
            pass

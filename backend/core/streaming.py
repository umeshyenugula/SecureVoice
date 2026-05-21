"""
Secure encrypted audio streaming.
Reads audio via the storage adapter (local or Cloudinary),
encrypts each chunk with AES-256-GCM, and yields JSON-encoded
chunk packets for WebSocket delivery.
"""
import json
import asyncio
from .encryption import encrypt_chunk, b64_to_key
from .storage    import stream_audio_bytes, get_audio_size


async def stream_encrypted_audio(session: dict):
    """
    Async generator — yields JSON-serialised encrypted chunk dicts.
    Session must contain:  key_b64, audio_file (storage key)
    """
    key         = b64_to_key(session["key_b64"])
    storage_key = session["audio_file"]

    total_size  = await get_audio_size(storage_key)

    chunk_index = 0
    async for raw in stream_audio_bytes(storage_key):
        packet          = encrypt_chunk(key, chunk_index, raw)
        packet["total"] = total_size
        yield json.dumps(packet)
        chunk_index += 1
        await asyncio.sleep(0)   # keep event loop responsive

    # Sentinel: signals end-of-stream to the client
    yield json.dumps({"index": -1, "nonce": "", "data": "", "total": total_size})

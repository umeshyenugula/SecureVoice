"""
AES-256-GCM Encryption module for secure audio chunk streaming.
Each chunk gets a unique nonce — no two chunks share encryption state.
"""
import os
import base64
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def generate_session_key() -> bytes:
    """Generate a cryptographically secure 256-bit AES key."""
    return os.urandom(32)


def encrypt_chunk(key: bytes, chunk_index: int, data: bytes) -> dict:
    """
    Encrypt a single audio chunk with AES-256-GCM.
    Returns dict with base64-encoded ciphertext and nonce.
    Each chunk uses a deterministic nonce derived from index + random salt
    to prevent nonce reuse while staying reproducible for streaming.
    """
    aesgcm = AESGCM(key)
    # 12-byte nonce: 4 bytes chunk index + 8 bytes random
    nonce = chunk_index.to_bytes(4, "big") + os.urandom(8)
    ciphertext = aesgcm.encrypt(nonce, data, associated_data=None)
    return {
        "index": chunk_index,
        "nonce": base64.b64encode(nonce).decode(),
        "data": base64.b64encode(ciphertext).decode(),
    }


def decrypt_chunk(key: bytes, nonce_b64: str, data_b64: str) -> bytes:
    """Decrypt a chunk on the frontend side (used in tests / server-side verify)."""
    aesgcm = AESGCM(key)
    nonce = base64.b64decode(nonce_b64)
    ciphertext = base64.b64decode(data_b64)
    return aesgcm.decrypt(nonce, ciphertext, associated_data=None)


def key_to_b64(key: bytes) -> str:
    return base64.b64encode(key).decode()


def b64_to_key(b64: str) -> bytes:
    return base64.b64decode(b64)

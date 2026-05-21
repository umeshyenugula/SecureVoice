/**
 * audio-player.js
 * Receives AES-256-GCM encrypted chunks over WebSocket.
 * Decrypts in-memory using Web Crypto API.
 * Plays via MediaSource Extensions (MSE) + Web Audio API — no visible controls.
 *
 * Bug fixes vs original:
 *  1. _sourceBuffer may not exist yet when first chunks arrive (sourceopen is async).
 *     Queue all chunks immediately; only flush after sourceopen fires.
 *  2. appendBuffer throws QuotaExceededError when the MSE buffer is full.
 *     Fixed by trimming the played-back portion before retrying.
 *  3. EOS sentinel arrived while SourceBuffer was still updating → endOfStream
 *     called on a busy buffer → InvalidStateError.
 *     Fixed by deferring EOS until updateend confirms idle.
 *  4. WAV files: MSE does not support audio/wav in most browsers.
 *     Fall back to a Blob-URL approach for WAV.
 *  5. _audioEl.play() called before sourceopen → AbortError on some browsers.
 *     Deferred until first updateend.
 *  6. MIME guessing missed AAC/M4A (ftyp box). Added.
 */

const SecurePlayer = (function () {
  'use strict';

  let _ws            = null;
  let _audioCtx      = null;
  let _sourceBuffer  = null;
  let _mediaSource   = null;
  let _audioEl       = null;
  let _onProgress    = null;
  let _onEnd         = null;
  let _onError       = null;
  let _totalBytes    = 0;
  let _receivedBytes = 0;
  let _pendingQueue  = [];   // Uint8Array chunks waiting to be appended; null = EOS
  let _isAppending   = false;
  let _eosQueued     = false;
  let _playStarted   = false;
  let _mseReady      = false;   // sourceopen has fired

  // ── AES-GCM key import ─────────────────────────────────────────────────────
  async function importKey(keyB64) {
    const raw = Uint8Array.from(atob(keyB64), c => c.charCodeAt(0));
    return crypto.subtle.importKey('raw', raw, { name: 'AES-GCM' }, false, ['decrypt']);
  }

  // ── Decrypt one chunk ──────────────────────────────────────────────────────
  async function decryptChunk(cryptoKey, nonceB64, dataB64) {
    const nonce      = Uint8Array.from(atob(nonceB64), c => c.charCodeAt(0));
    const ciphertext = Uint8Array.from(atob(dataB64),  c => c.charCodeAt(0));
    const plaintext  = await crypto.subtle.decrypt(
      { name: 'AES-GCM', iv: nonce }, cryptoKey, ciphertext
    );
    return new Uint8Array(plaintext);
  }

  // ── MIME detection ─────────────────────────────────────────────────────────
  function _guessMime(chunk) {
    const b = chunk;
    // MP3: ID3 tag or sync word
    if (b[0] === 0x49 && b[1] === 0x44 && b[2] === 0x33) return 'audio/mpeg'; // ID3
    if (b[0] === 0xFF && (b[1] & 0xE0) === 0xE0)          return 'audio/mpeg'; // sync
    // OGG
    if (b[0] === 0x4F && b[1] === 0x67 && b[2] === 0x67 && b[3] === 0x53) return 'audio/ogg; codecs=opus';
    // AAC / M4A (ftyp box at offset 4)
    if (b[4] === 0x66 && b[5] === 0x74 && b[6] === 0x79 && b[7] === 0x70) return 'audio/mp4';
    // ADTS AAC
    if (b[0] === 0xFF && (b[1] & 0xF0) === 0xF0) return 'audio/aac';
    // WAV — MSE doesn't support it; handled separately
    if (b[0] === 0x52 && b[1] === 0x49 && b[2] === 0x46 && b[3] === 0x46) return 'audio/wav';
    return 'audio/mpeg'; // safe fallback
  }

  // ── Evict already-played data to free buffer quota ─────────────────────────
  function _evictPlayed() {
    if (!_sourceBuffer || !_audioEl) return;
    const buffered = _sourceBuffer.buffered;
    if (buffered.length === 0) return;
    const currentTime = _audioEl.currentTime;
    const start       = buffered.start(0);
    // Keep 2 s behind current position as cushion
    const evictEnd = Math.max(start, currentTime - 2);
    if (evictEnd > start + 0.1) {
      try {
        _sourceBuffer.remove(start, evictEnd);
      } catch (_) {}
    }
  }

  // ── Flush queue into SourceBuffer ──────────────────────────────────────────
  function _flushQueue() {
    if (!_mseReady || !_sourceBuffer || _isAppending) return;
    if (_sourceBuffer.updating) return;
    if (_pendingQueue.length === 0) {
      // Nothing left — if EOS was signalled, apply it now
      if (_eosQueued && _mediaSource && _mediaSource.readyState === 'open') {
        _eosQueued = false;
        try { _mediaSource.endOfStream(); } catch (_) {}
      }
      return;
    }

    const chunk = _pendingQueue[0];

    // null sentinel = EOS
    if (chunk === null) {
      _pendingQueue.shift();
      if (_mediaSource && _mediaSource.readyState === 'open') {
        try { _mediaSource.endOfStream(); } catch (_) {
          // buffer still updating — defer to next updateend
          _eosQueued = true;
        }
      }
      return;
    }

    _isAppending = true;
    try {
      _sourceBuffer.appendBuffer(chunk);
      _pendingQueue.shift();
    } catch (e) {
      _isAppending = false;
      if (e.name === 'QuotaExceededError') {
        // Buffer full — evict old data then retry on next updateend
        _evictPlayed();
        // Will retry via updateend once eviction completes
      } else {
        // Real error — report it
        if (_onError) _onError('Buffer append failed: ' + e.message);
      }
    }
  }

  // ── Initialise MSE pipeline ────────────────────────────────────────────────
  function _initMSE(mimeType) {
    _mediaSource = new MediaSource();
    _audioEl     = document.createElement('audio');
    _audioEl.src = URL.createObjectURL(_mediaSource);
    _audioEl.style.display = 'none';
    document.body.appendChild(_audioEl);

    _mediaSource.addEventListener('sourceopen', () => {
      // Verify browser actually supports this MIME before adding
      if (!MediaSource.isTypeSupported(mimeType)) {
        // Try mp4 as fallback for AAC content
        const fallback = 'audio/mp4';
        if (mimeType !== fallback && MediaSource.isTypeSupported(fallback)) {
          mimeType = fallback;
        } else {
          if (_onError) _onError('Your browser does not support this audio format.');
          return;
        }
      }

      _sourceBuffer = _mediaSource.addSourceBuffer(mimeType);
      _mseReady     = true;

      _sourceBuffer.addEventListener('updateend', () => {
        _isAppending = false;
        // Start playback on first successful append
        if (!_playStarted && _audioEl) {
          _playStarted = true;
          _audioEl.play().catch(() => {});
        }
        _flushQueue();
      });

      _sourceBuffer.addEventListener('error', (e) => {
        if (_onError) _onError('SourceBuffer error — audio format may be unsupported.');
      });

      // Flush anything that queued up while waiting for sourceopen
      _flushQueue();
    });

    _audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    const src = _audioCtx.createMediaElementSource(_audioEl);
    src.connect(_audioCtx.destination);

    _audioEl.addEventListener('ended', () => {
      _cleanup();
      if (_onEnd) _onEnd();
    });
  }

  // ── WAV fallback (MSE doesn't support WAV in most browsers) ───────────────
  // Collects all chunks, builds a Blob, plays it directly.
  let _wavChunks = [];
  let _isWav     = false;

  function _initWavFallback() {
    _isWav    = true;
    _wavChunks = [];
    _audioEl  = document.createElement('audio');
    _audioEl.style.display = 'none';
    document.body.appendChild(_audioEl);

    _audioCtx = new (window.AudioContext || window.webkitAudioContext)();

    _audioEl.addEventListener('ended', () => {
      _cleanup();
      if (_onEnd) _onEnd();
    });
  }

  function _flushWav() {
    if (!_isWav) return;
    const blob = new Blob(_wavChunks, { type: 'audio/wav' });
    _audioEl.src = URL.createObjectURL(blob);
    const src = _audioCtx.createMediaElementSource(_audioEl);
    src.connect(_audioCtx.destination);
    _audioEl.play().catch(() => {});
  }

  // ── Cleanup ────────────────────────────────────────────────────────────────
  function _cleanup() {
    if (_ws)       { try { _ws.close(); } catch (_) {} _ws = null; }
    if (_audioCtx) { try { _audioCtx.close(); } catch (_) {} _audioCtx = null; }
    if (_audioEl)  { _audioEl.src = ''; _audioEl.remove(); _audioEl = null; }
    _sourceBuffer  = null;
    _mediaSource   = null;
    _pendingQueue  = [];
    _wavChunks     = [];
    _isAppending   = false;
    _eosQueued     = false;
    _playStarted   = false;
    _mseReady      = false;
    _isWav         = false;
  }

  // ── Public: play ───────────────────────────────────────────────────────────
  async function play(sessionId, keyB64, wsBaseUrl, { onProgress, onEnd, onError } = {}) {
    _onProgress = onProgress;
    _onEnd      = onEnd;
    _onError    = onError;

    const cryptoKey  = await importKey(keyB64);
    let   mimeSet    = false;

    const wsUrl = `${wsBaseUrl}/ws/stream/${sessionId}`;
    _ws = new WebSocket(wsUrl);

    _ws.onmessage = async (evt) => {
      let packet;
      try { packet = JSON.parse(evt.data); }
      catch (e) { if (_onError) _onError('Bad packet from server.'); return; }

      if (packet.error) {
        if (_onError) _onError(packet.message || packet.error);
        _cleanup();
        return;
      }

      // EOS sentinel
      if (packet.index === -1) {
        if (_isWav) {
          _flushWav();
        } else {
          _pendingQueue.push(null);
          _flushQueue();
        }
        return;
      }

      _totalBytes = packet.total || _totalBytes;

      // Decrypt
      let plain;
      try {
        plain = await decryptChunk(cryptoKey, packet.nonce, packet.data);
      } catch (e) {
        if (_onError) _onError('Decryption failed — key mismatch or corrupted chunk.');
        _cleanup();
        return;
      }

      _receivedBytes += plain.byteLength;

      // First chunk: detect format and init pipeline
      if (!mimeSet) {
        mimeSet       = true;
        const mime    = _guessMime(plain);
        if (mime === 'audio/wav') {
          _initWavFallback();
        } else {
          _initMSE(mime);
        }
      }

      if (_isWav) {
        _wavChunks.push(plain);
      } else {
        _pendingQueue.push(plain);
        _flushQueue();
      }

      if (_onProgress && _totalBytes > 0) {
        _onProgress(Math.min(1, _receivedBytes / _totalBytes));
      }
    };

    _ws.onerror = () => {
      if (_onError) _onError('WebSocket connection failed.');
      _cleanup();
    };

    _ws.onclose = () => {};
  }

  // ── Public: stop ──────────────────────────────────────────────────────────
  function stop() { _cleanup(); }

  // ── Security hooks ─────────────────────────────────────────────────────────
  window.addEventListener('sv:tab-hidden', () => {
    if (_audioEl) {
      stop();
      if (_onError) _onError('Playback terminated: tab switched.');
    }
  });

  window.addEventListener('sv:devtools-open', () => {
    if (_audioEl) {
      stop();
      if (_onError) _onError('Playback terminated: inspection detected.');
    }
  });

  return { play, stop };
})();

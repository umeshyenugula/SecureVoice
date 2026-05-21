/**
 * face-verify.js
 * Wraps face-api.js for live face detection and embedding comparison.
 * Models are loaded from CDN (jsdelivr).
 */

const FaceVerify = (function () {
  'use strict';

  const MODEL_URL = 'https://cdn.jsdelivr.net/npm/@vladmandic/face-api/model/';
  let _modelsLoaded = false;

  // ── Load models ─────────────────────────────────────────────────────────────
  async function loadModels() {
    if (_modelsLoaded) return;
    await Promise.all([
      faceapi.nets.tinyFaceDetector.loadFromUri(MODEL_URL),
      faceapi.nets.faceLandmark68TinyNet.loadFromUri(MODEL_URL),
      faceapi.nets.faceRecognitionNet.loadFromUri(MODEL_URL),
    ]);
    _modelsLoaded = true;
  }

  // ── Start camera ────────────────────────────────────────────────────────────
  async function startCamera(videoEl) {
    const stream = await navigator.mediaDevices.getUserMedia({
      video: { width: 420, height: 420, facingMode: 'user' },
      audio: false,
    });
    videoEl.srcObject = stream;
    await new Promise(resolve => { videoEl.onloadedmetadata = resolve; });
    await videoEl.play();
    return stream;
  }

  // ── Stop camera ─────────────────────────────────────────────────────────────
  function stopCamera(stream) {
    if (stream) stream.getTracks().forEach(t => t.stop());
  }

  // ── Detect and get descriptor ────────────────────────────────────────────────
  async function getDescriptor(videoEl) {
    const detection = await faceapi
      .detectSingleFace(videoEl, new faceapi.TinyFaceDetectorOptions({ scoreThreshold: 0.5 }))
      .withFaceLandmarks(true)
      .withFaceDescriptor();
    return detection ? Array.from(detection.descriptor) : null;
  }

  // ── Continuous scanning loop with callback ───────────────────────────────────
  async function scanLoop(videoEl, canvasEl, onDetect) {
    const displaySize = { width: videoEl.clientWidth, height: videoEl.clientHeight };
    faceapi.matchDimensions(canvasEl, displaySize);

    let running = true;
    let foundCount = 0;
    const REQUIRED_STABLE = 8;   // face must be stable for N frames (higher = more reliable embedding)

    async function tick() {
      if (!running) return;
      try {
        const detection = await faceapi
          .detectSingleFace(videoEl, new faceapi.TinyFaceDetectorOptions({ scoreThreshold: 0.7 }))
          .withFaceLandmarks(true)
          .withFaceDescriptor();

        const ctx = canvasEl.getContext('2d');
        ctx.clearRect(0, 0, canvasEl.width, canvasEl.height);

        if (detection) {
          const resized = faceapi.resizeResults(detection, displaySize);
          // Draw subtle landmark dots
          ctx.fillStyle = 'rgba(26,25,22,0.4)';
          resized.landmarks.positions.forEach(pt => {
            ctx.beginPath();
            ctx.arc(pt.x, pt.y, 1.5, 0, 2 * Math.PI);
            ctx.fill();
          });
          foundCount++;
          if (foundCount >= REQUIRED_STABLE) {
            running = false;
            onDetect(Array.from(detection.descriptor));
            return;
          }
        } else {
          foundCount = 0;
        }
      } catch (_) { /* ignore frame errors */ }

      if (running) requestAnimationFrame(tick);
    }

    requestAnimationFrame(tick);
    return () => { running = false; };
  }

  // ── Euclidean distance ───────────────────────────────────────────────────────
  function distance(a, b) {
    return Math.sqrt(a.reduce((sum, v, i) => sum + (v - b[i]) ** 2, 0));
  }

  return { loadModels, startCamera, stopCamera, scanLoop, getDescriptor, distance };
})();

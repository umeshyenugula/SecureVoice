/**
 * security.js — Anti-inspection, tab-change detection, keyboard traps.
 * Import this before any other script.
 */

(function () {
  'use strict';

  // ── Disable right-click ───────────────────────────────────────────────────
  document.addEventListener('contextmenu', e => e.preventDefault());

  // ── Block dangerous keyboard shortcuts ───────────────────────────────────
  document.addEventListener('keydown', e => {
    // F12
    if (e.key === 'F12') { e.preventDefault(); return false; }
    // Ctrl+Shift+I / J / C  (DevTools)
    if (e.ctrlKey && e.shiftKey && ['i','I','j','J','c','C'].includes(e.key)) {
      e.preventDefault(); return false;
    }
    // Ctrl+U (view source)
    if (e.ctrlKey && e.key === 'u') { e.preventDefault(); return false; }
    // Ctrl+S (save page)
    if (e.ctrlKey && e.key === 's') { e.preventDefault(); return false; }
    // Ctrl+P (print)
    if (e.ctrlKey && e.key === 'p') { e.preventDefault(); return false; }
  });

  // ── DevTools size-based detection ─────────────────────────────────────────
  const THRESHOLD = 160;
  let _devToolsOpen = false;

  function detectDevTools() {
    const widthDiff  = window.outerWidth  - window.innerWidth;
    const heightDiff = window.outerHeight - window.innerHeight;
    const opened = widthDiff > THRESHOLD || heightDiff > THRESHOLD;
    if (opened && !_devToolsOpen) {
      _devToolsOpen = true;
      window.dispatchEvent(new CustomEvent('sv:devtools-open'));
    } else if (!opened && _devToolsOpen) {
      _devToolsOpen = false;
    }
  }

  setInterval(detectDevTools, 1000);

  // ── Tab / visibility change ───────────────────────────────────────────────
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) {
      window.dispatchEvent(new CustomEvent('sv:tab-hidden'));
    }
  });

  // ── Expose state ──────────────────────────────────────────────────────────
  window.SVSecurity = {
    isDevToolsOpen: () => _devToolsOpen,
  };
})();

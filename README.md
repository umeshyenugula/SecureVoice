# SecureVoice 🔒

A **single-use, encrypted, face-verified** private voice message delivery system.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│  BROWSER (Frontend)                                                  │
│                                                                      │
│  1. Open /listen/<token>                                             │
│  2. Face verified via face-api.js (client-side + server comparison) │
│  3. Receive AES-256-GCM key over HTTPS                              │
│  4. Audio streams as encrypted chunks over WebSocket                │
│  5. Decrypt in-memory using Web Crypto API                          │
│  6. Play via MediaSource Extensions — no downloadable URL           │
└──────────────────────────┬──────────────────────────────────────────┘
                           │ HTTPS / WSS
┌──────────────────────────▼──────────────────────────────────────────┐
│  FASTAPI BACKEND                                                     │
│                                                                      │
│  POST /api/verify-face    → validate face, issue session + AES key  │
│  POST /api/playback/start → expire token immediately                │
│  WS   /ws/stream/{id}     → stream encrypted audio chunks           │
│  POST /api/playback/done  → destroy session key                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Project Structure

```
securevoice/
├── backend/
│   ├── main.py                    # FastAPI app entrypoint
│   ├── api/
│   │   └── routes.py              # REST API routes
│   ├── websockets/
│   │   └── stream_handler.py      # WebSocket streaming
│   ├── core/
│   │   ├── encryption.py          # AES-256-GCM chunk encryption
│   │   ├── tokens.py              # Token/session lifecycle
│   │   └── streaming.py          # Encrypted audio streamer
│   ├── middleware/
│   │   └── security.py            # CSP, CORS, rate limiting
│   └── models/
│       └── schemas.py             # Pydantic models + DB schemas
├── frontend/
│   ├── index.html                 # Main player page
│   ├── css/
│   │   └── style.css              # Premium white minimalist design
│   ├── js/
│   │   ├── security.js            # Anti-inspection, keyboard traps
│   │   ├── face-verify.js         # face-api.js wrapper
│   │   └── audio-player.js       # Encrypted MSE + Web Audio player
│   └── pages/
│       ├── expired.html           # Expired message page
│       └── admin.html             # Token creation + audio upload
├── uploads/                       # Audio files (gitignored)
├── keys/                          # Key storage (gitignored, use vault in prod)
└── requirements.txt
```

---

## Quick Start

### 1. Install dependencies

```bash
cd securevoice
pip install -r requirements.txt
```

### 2. Run the server

```bash
uvicorn backend.main:app --reload --port 8000
```

### 3. Create a message

1. Open `http://localhost:8000/admin`
2. Upload an audio file (MP3, WAV, OGG, M4A, AAC — max 50 MB)
3. Click **Open Camera**, have the recipient face the camera, then **Capture Face**
4. Click **Generate Link** — copy the one-time URL

### 4. Send to recipient

Share the `/listen/<token>` URL privately. The recipient:
- Opens the link
- Allows camera access
- Passes face verification
- Hears the message exactly once

---

## Security Architecture

### Token Lifecycle
```
Admin creates token → Link is live (until playback starts)
                      ↓
                 User opens link → token NOT expired yet (refresh-safe)
                      ↓
           Face verification → session key issued
                      ↓
           Playback START called → token PERMANENTLY expired
                      ↓
           Audio streams encrypted → decrypted in-memory only
                      ↓
           Playback ends → session + AES key destroyed
```

### Encryption
- **AES-256-GCM** per chunk
- Unique 12-byte nonce per chunk (4-byte index + 8-byte random)
- Key is ephemeral — generated per session, never stored to disk
- Key transmitted once over HTTPS then used only in-browser via Web Crypto API

### Anti-Replay
- Token marked `used=True` atomically on playback start
- Session has `started` flag — second call returns 403
- Session TTL: 1 hour from creation

### Anti-Inspection
- Right-click disabled
- F12 / Ctrl+Shift+I / Ctrl+U / Ctrl+S blocked
- DevTools size-change detection → playback terminates
- Tab switch → playback terminates
- No audio element visible in DOM (Web Audio API)
- No direct audio URL (WebSocket stream only)
- CSP headers block external script injection

### Headers
```
X-Frame-Options: DENY
X-Content-Type-Options: nosniff
Content-Security-Policy: (strict)
Cache-Control: no-store
Strict-Transport-Security: max-age=31536000
```

---

## Cloud Deployment (Render + Cloudinary)

This is the recommended way to deploy so you can create links from anywhere
and share them — no local server needed.

### Step 1 — Cloudinary (free audio storage)

1. Sign up at **https://cloudinary.com** (free tier: 25 GB storage / 25 GB bandwidth)
2. Go to your Dashboard → copy the **API Environment variable**
   It looks like: `cloudinary://874321098765432:AbCdEfGhIjKlMnOpQrStUv@your-cloud-name`
3. Paste it as `CLOUDINARY_URL` in your environment (see Step 3)

### Step 2 — MongoDB Atlas (free token/session storage)

1. Sign up at **https://mongodb.com/cloud/atlas** (free M0 tier)
2. Create a cluster → Database Access → add a user with readWrite
3. Network Access → Allow from anywhere (`0.0.0.0/0`) for cloud deployments
4. Connect → Drivers → copy the connection string
   Replace `<password>` with your user's password

### Step 3 — Deploy to Render (free tier, HTTPS included)

1. Push your project to a GitHub repo
2. Go to **https://render.com** → New → Web Service → connect your repo
3. Set these values:
   - **Build command:** `pip install -r securevoice/requirements.txt`
   - **Start command:** `uvicorn backend.main:app --host 0.0.0.0 --port $PORT`
   - **Root directory:** `securevoice`
4. Under **Environment Variables** add:
   ```
   CLOUDINARY_URL   = cloudinary://key:secret@cloud_name
   MONGO_URI        = mongodb+srv://user:pass@cluster.mongodb.net/securevoice?retryWrites=true&w=majority
   MONGO_DB_NAME    = securevoice
   ALLOWED_ORIGINS  = https://your-app.onrender.com
   SECRET_SALT      = <run: python -c "import secrets; print(secrets.token_hex(32))">
   FACE_THRESHOLD   = 0.40
   ```
5. Deploy — Render gives you a public HTTPS URL like `https://securevoice-xyz.onrender.com`

### Step 4 — Use it

1. Open `https://your-app.onrender.com/admin`
2. Upload audio → it goes straight to Cloudinary
3. Capture recipient's face
4. Generate Link → share the URL with the recipient

---

## Production Deployment

### 1. Use HTTPS (required for camera + Web Crypto)
```bash
# With Caddy (recommended)
caddy reverse-proxy --from yourdomain.com --to localhost:8000

# Or with nginx + certbot
# See: https://certbot.eff.org/
```

### 2. Persistent token storage (MongoDB)
Uncomment and configure the motor section in `backend/models/schemas.py`:
```bash
pip install motor
export MONGO_URI=mongodb+srv://user:pass@cluster.mongodb.net/securevoice
```
Then replace in-memory store calls in `core/tokens.py` with MongoDB operations.

### 3. Environment variables
```bash
export MONGO_URI=...
export ALLOWED_ORIGINS=https://yourdomain.com
export SECRET_SALT=<32-byte-random-hex>
```

### 4. Production server
```bash
pip install gunicorn
gunicorn backend.main:app -w 2 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000
```

### 5. IP/device locking
The `create_token` call already records `ip_lock`. To enforce it, add a check in
`routes.py → verify_face`:
```python
if token["ip_lock"] and token["ip_lock"] != request.client.host:
    raise HTTPException(403, "IP mismatch.")
```

---

## Face Verification Tuning

The threshold in `routes.py` controls how strict the face matching is:
```python
FACE_SIMILARITY_THRESHOLD = 0.50  # Euclidean distance (lower = stricter)
```
- `0.40` — very strict (may reject valid users in poor lighting)
- `0.50` — balanced (recommended)
- `0.60` — lenient (use only if lighting is controlled)

---

## Limitations & Notes

- **In-memory token store** resets on server restart. Use MongoDB/Redis for production.
- Face-api.js models are loaded from CDN. Self-host them for air-gapped deployments.
- MSE mime-type detection is heuristic — test your audio format. MP3 is most compatible.
- Audio autoplay may require a user gesture on some browsers (the "Allow Camera" click satisfies this).

---

## License
MIT — private use, production hardening recommended before public deployment.

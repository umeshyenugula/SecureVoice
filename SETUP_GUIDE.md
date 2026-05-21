# SecureVoice — Complete Setup Guide

---

## STEP 1 — Get your MongoDB URI

### Option A: MongoDB Atlas (Free Cloud — Recommended)

1. Go to https://cloud.mongodb.com and sign up / log in
2. Click **"Build a Database"** → choose **Free (M0)**
3. Pick a cloud provider (AWS/GCP/Azure) and region → click **Create**
4. Under **Security → Database Access** → click **"Add New Database User"**
   - Username: `securevoice_user`
   - Password: click **Autogenerate** → copy the password
   - Role: **Read and Write to any database**
   - Click **Add User**
5. Under **Security → Network Access** → click **"Add IP Address"**
   - For development: click **"Allow Access From Anywhere"** (0.0.0.0/0)
   - For production: add your server's actual IP
6. Under **Deployment → Database** → click **Connect** on your cluster
   - Choose **"Drivers"** → Driver: Python, Version: 3.12+
   - Copy the connection string — it looks like:
     ```
     mongodb+srv://securevoice_user:<password>@cluster0.abc123.mongodb.net/?retryWrites=true&w=majority
     ```
   - Replace `<password>` with the password you copied in step 4
   - Add your database name before the `?`:
     ```
     mongodb+srv://securevoice_user:YOUR_PASSWORD@cluster0.abc123.mongodb.net/securevoice?retryWrites=true&w=majority
     ```

### Option B: Local MongoDB

1. Install MongoDB Community: https://www.mongodb.com/try/download/community
2. Start it: `mongod --dbpath /data/db`
3. Your URI is simply: `mongodb://localhost:27017`

---

## STEP 2 — Configure your .env file

Open the `.env` file in the project root and fill in your values:

```env
# Paste your full Atlas URI here (or mongodb://localhost:27017 for local)
MONGO_URI=mongodb+srv://securevoice_user:YOUR_PASSWORD@cluster0.abc123.mongodb.net/securevoice?retryWrites=true&w=majority

# Database name (leave as securevoice unless you want something else)
MONGO_DB_NAME=securevoice

# Generate a random secret — run this in your terminal:
# python -c "import secrets; print(secrets.token_hex(32))"
SECRET_SALT=paste_the_output_here

# Your domain(s) — for local dev leave as-is
ALLOWED_ORIGINS=http://localhost:8000,http://127.0.0.1:8000

# Face match strictness (0.40=strict, 0.50=balanced, 0.60=lenient)
FACE_THRESHOLD=0.50

# Max audio upload size in MB
MAX_UPLOAD_MB=50
```

---

## STEP 3 — Install Python dependencies

```bash
# Navigate to the project folder
cd securevoice

# (Recommended) Create a virtual environment
python -m venv venv

# Activate it
# On Windows:
venv\Scripts\activate
# On Mac/Linux:
source venv/bin/activate

# Install all packages
pip install -r requirements.txt
```

---

## STEP 4 — Run the server

```bash
uvicorn backend.main:app --reload --port 8000
```

You should see:
```
INFO:     Started server process
INFO:     Uvicorn running on http://127.0.0.1:8000
```

---

## STEP 5 — Test MongoDB connection

Open a Python shell and run:

```python
import asyncio, motor.motor_asyncio, os
from dotenv import load_dotenv
load_dotenv()

async def test():
    client = motor.motor_asyncio.AsyncIOMotorClient(os.getenv("MONGO_URI"))
    db = client[os.getenv("MONGO_DB_NAME", "securevoice")]
    await db["test"].insert_one({"ping": True})
    doc = await db["test"].find_one({"ping": True})
    print("✓ MongoDB connected:", doc)
    await db["test"].drop()

asyncio.run(test())
```

If you see `✓ MongoDB connected` — you're all set.

---

## STEP 6 — Create your first message

1. Open http://localhost:8000/admin
2. Upload an MP3/WAV audio file
3. Have the recipient face the camera → click **Capture Face**
4. Click **Generate Link** → copy the `/listen/xxxx` URL
5. Send the URL to the recipient privately

---

## Project File Map

```
securevoice/
│
├── .env                          ← ★ YOUR CREDENTIALS GO HERE ★
├── requirements.txt              ← Python packages
│
├── backend/
│   ├── main.py                   ← Loads .env, starts FastAPI
│   ├── api/routes.py             ← All REST endpoints
│   ├── websockets/
│   │   └── stream_handler.py     ← Encrypted audio stream over WebSocket
│   ├── core/
│   │   ├── tokens.py             ← MongoDB token + session logic
│   │   ├── encryption.py         ← AES-256-GCM
│   │   └── streaming.py          ← Chunk reader + encryptor
│   ├── middleware/security.py    ← CSP, CORS, rate limiting
│   └── models/schemas.py        ← Pydantic request/response models
│
├── frontend/
│   ├── index.html                ← Player page (/listen/<token>)
│   ├── pages/
│   │   ├── admin.html            ← Create messages
│   │   └── expired.html         ← Shown after message is used
│   ├── css/style.css             ← White minimalist UI
│   └── js/
│       ├── security.js           ← Anti-devtools, keyboard traps
│       ├── face-verify.js        ← face-api.js wrapper
│       └── audio-player.js      ← WebSocket + decrypt + MSE playback
│
└── uploads/                      ← Audio files stored here (gitignored)
```

---

## Where credentials live — summary

| What | Where |
|------|-------|
| MongoDB connection string | `.env` → `MONGO_URI` |
| Database name | `.env` → `MONGO_DB_NAME` |
| Face threshold | `.env` → `FACE_THRESHOLD` |
| Secret salt | `.env` → `SECRET_SALT` |
| CORS origins | `.env` → `ALLOWED_ORIGINS` |

The `.env` file is read automatically when the server starts via `python-dotenv`.
You never need to hardcode credentials anywhere in the Python files.

---

## Production Checklist

- [ ] HTTPS enabled (required for camera + Web Crypto API)
- [ ] `.env` not committed to git (it's in `.gitignore`)
- [ ] MongoDB Atlas Network Access locked to your server IP (not 0.0.0.0/0)
- [ ] `SECRET_SALT` is a real random 64-char hex string
- [ ] `ALLOWED_ORIGINS` set to your real domain
- [ ] `uvicorn` running behind nginx or Caddy reverse proxy
- [ ] `uploads/` folder is on persistent storage (not ephemeral)

---

## Common Errors

**`Authentication failed` from MongoDB**
→ Wrong password in MONGO_URI. Re-check Atlas → Database Access.

**`ServerSelectionTimeoutError`**
→ Your IP is not whitelisted. Atlas → Network Access → Add your IP.

**Camera not working**
→ Requires HTTPS in production. Works on `localhost` without HTTPS.

**Face not detected**
→ Ensure good lighting, face centered, no glasses/mask. Lower `FACE_THRESHOLD` to 0.60 if needed.

**Audio not playing**
→ MP3 has the best MSE browser support. Try converting to MP3 if using WAV/OGG.

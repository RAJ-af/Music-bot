# Telegram Music Bot

A free Telegram bot that plays music in voice chats from YouTube, YouTube Music, and Spotify.

## Features
- **Multi-source**: YouTube, YouTube Music (via ytmusicapi), Spotify (via spotdl)
- **Commands**: `/play`, `/search`, `/skip`, `/queue`, `/stop`, `/pause`, `/resume`, `/volume`
- **Smart detection**: Auto-detects URLs (YouTube, Spotify, YouTube Music) or searches by name
- **Queue support** with inline selection
- **Chunked streaming** via PyTgCalls + FFmpeg - no full download needed
- **100% Free** - no paid APIs required

## Local Setup

### 1. Get Telegram API Credentials
- Go to https://my.telegram.org → Create Application
- Get **API_ID** and **API_HASH**

### 2. Create Bot Token
- Message @BotFather → `/newbot`
- Get **BOT_TOKEN**

### 3. (Optional) Spotify API for better Spotify search
- Go to https://developer.spotify.com/dashboard
- Create App → Get **Client ID** and **Client Secret**
- Add to `.env` as `SPOTIFY_CLIENT_ID` and `SPOTIFY_CLIENT_SECRET`

### 4. Generate Session String (for voice chat)
```bash
pip install pyrogram tgcrypto
python -c "
from pyrogram import Client
app = Client('userbot', api_id=YOUR_API_ID, api_hash='YOUR_API_HASH')
app.start()
print(app.export_session_string())
app.stop()
"
```
Copy the output to `SESSION_STRING` in `.env`

### 5. Configure Environment
```bash
cp .env.example .env
# Edit .env with your credentials
```

### 6. Install Dependencies
```bash
pip install -r requirements.txt
# Need ffmpeg & system deps: sudo apt install ffmpeg cmake rustc cargo
```

### 7. Run
```bash
python bot.py
```

## Railway Deployment (Recommended)

### 1. Push to GitHub
```bash
git init
git add .
git commit -m "Initial commit"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/music-bot.git
git push -u origin main
```

### 2. Deploy on Railway
1. Go to https://railway.app → New Project → Deploy from GitHub
2. Select your repo
3. Add environment variables in Railway dashboard:
   - `BOT_TOKEN` - Your bot token from @BotFather
   - `API_ID` - Your Telegram API ID
   - `API_HASH` - Your Telegram API Hash
   - `SESSION_STRING` - Generate with Pyrogram (see step 4 above)
   - `SPOTIFY_CLIENT_ID` - Optional, for better Spotify search
   - `SPOTIFY_CLIENT_SECRET` - Optional

4. Railway will auto-detect `nixpacks.toml` and install everything including:
   - Python 3.11
   - ffmpeg
   - cmake & Rust (for pytgcalls native deps)
   - All Python packages

5. Deploy! Railway runs `python bot.py` as a worker service.

### 3. Generate SESSION_STRING for Railway
Run locally once (or in Railway shell):
```bash
python -c "
from pyrogram import Client
app = Client('userbot', api_id=YOUR_API_ID, api_hash='YOUR_API_HASH')
app.start()
print(app.export_session_string())
app.stop()
"
```
Copy output → Add as `SESSION_STRING` in Railway env vars → Redeploy.

## Commands

| Command | Description |
|---------|-------------|
| `/play <name/URL>` | Play song (YouTube, Spotify, YT Music URLs or search) |
| `/search <query>` | Search all sources & pick result |
| `/skip` | Skip current track |
| `/queue` | Show queue |
| `/stop` | Stop & leave voice chat |
| `/pause` | Pause playback |
| `/resume` | Resume playback |
| `/volume <1-100>` | Set volume |

## Supported URLs

- **YouTube**: `youtube.com/watch?v=...`, `youtu.be/...`
- **Spotify**: `spotify.com/track/...`, `spotify.com/album/...`, `spotify.com/playlist/...`
- **YouTube Music**: `music.youtube.com/watch?v=...`

## How it works

- **YouTube/YTMusic**: `yt-dlp` gets direct audio stream URL → PyTgCalls streams in chunks via FFmpeg
- **Spotify**: `spotdl` finds YouTube equivalent → streams via `yt-dlp` (no Spotify API streaming)
- All audio streams in real-time chunks, no full download stored

## Notes

- The userbot account must be in the voice chat to stream audio
- Bot and userbot can be the same account (use session string)
- For 24/7 hosting, use Railway (free tier available) or VPS
- Spotify playlist/album support: just send the URL, bot will queue all tracks
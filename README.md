# 📦 TG Cloud

**Free unlimited cloud storage for your home videos, powered by Telegram.**

Upload videos of any size - they're automatically split into 1.9GB chunks, uploaded to your private Telegram channel, and reassembled when you download.

## How it works

```
Your 15GB video
      │
      ▼
┌─────────────┐
│   Chunker   │  Splits into 1.9GB pieces
└─────────────┘
      │
      ▼
┌─────────────────────────────────────────┐
│     Your Private Telegram Channel       │
│  chunk_0.mp4 (1.9GB)                   │
│  chunk_1.mp4 (1.9GB)                   │
│  chunk_2.mp4 (1.9GB)                   │
│  ...                                    │
└─────────────────────────────────────────┘
      │
      ▼
┌─────────────┐
│  Reassemble │  Downloads & merges chunks
└─────────────┘
      │
      ▼
Your original 15GB video (byte-for-byte identical)
```

## Setup (5 minutes)

### 1. Get Telegram API Credentials

1. Go to https://my.telegram.org/apps
2. Log in with your phone number
3. Create a new application (any name/description)
4. Copy your `api_id` and `api_hash`

### 2. Create a Private Channel

1. Open Telegram
2. Create a new **private** channel (name it whatever)
3. Go to https://web.telegram.org
4. Open your new channel
5. Look at the URL: `web.telegram.org/k/#-100XXXXXXXXXX`
6. Copy the number starting with `-100` (this is your channel ID)

### 3. Install & Configure

```bash
# Clone or download this folder
cd tg_cloud

# Install dependencies
pip install telethon flask

# Set environment variables
export TG_API_ID="your_api_id"
export TG_API_HASH="your_api_hash"
export TG_CHANNEL_ID="-100xxxxxxxxxx"
```

### 4. First Run (Authentication)

```bash
python cli.py list
```

First time running, Telegram will:
1. Send you a login code via Telegram
2. Ask for the code
3. Create a `tg_cloud.session` file (keep this safe!)

## Usage

### Web Interface

```bash
python app.py
# Open http://localhost:5000
```

Drag & drop files, see progress, download/delete files.

### CLI (recommended for bulk)

```bash
# List all stored files
python cli.py list

# Upload a single file
python cli.py upload -f "/path/to/video.mp4"

# Upload entire folder of videos
python cli.py bulk-upload -d "/path/to/videos"

# Download a file (use ID from list)
python cli.py download --id 5 -o /path/to/output

# Delete a file
python cli.py delete --id 5
```

### Bulk Upload Your 1000 Videos

```bash
# Upload all videos from a directory (recursive)
python cli.py bulk-upload -d "/mnt/videos" -e ".mp4,.mov,.avi,.mkv"

# This will:
# - Find all video files
# - Show total count and size
# - Upload each one, splitting as needed
# - Track everything in the database
```

## Hosting the Frontend on Namecheap

Your Namecheap shared hosting likely can't run Python directly. Options:

### Option A: Run backend elsewhere, static frontend on Namecheap

1. Run the Python backend on a VPS ($5/mo DigitalOcean) or your home PC
2. Modify the frontend to point to your backend's public URL
3. Upload the HTML to Namecheap

### Option B: Cloudflare Tunnel (free, runs from your PC)

1. Install `cloudflared` on your PC
2. Run: `cloudflared tunnel --url http://localhost:5000`
3. Get a free public URL
4. Point your Namecheap domain to it

### Option C: Free tier VPS

- Oracle Cloud free tier (forever free)
- Google Cloud free tier
- Fly.io free tier

## Files

```
tg_cloud/
├── tg_storage.py   # Core storage engine
├── app.py          # Flask web server + UI
├── cli.py          # Command line tool
├── files.db        # SQLite database (auto-created)
├── tg_cloud.session # Telegram session (auto-created)
└── setup.sh        # Setup helper
```

## Important Notes

- **Keep `tg_cloud.session` safe** - it's your Telegram login
- **Keep `files.db` safe** - it maps files to their chunks
- Telegram stores files forever (no auto-deletion)
- No re-encoding - you get byte-for-byte original files back
- Upload speed depends on your internet (Telegram doesn't throttle)

## Limits

- 2GB per chunk (we use 1.9GB to be safe)
- Unlimited total storage
- No file type restrictions
- Telegram rate limits: ~30 messages/second (plenty fast)

## License

MIT - do whatever you want

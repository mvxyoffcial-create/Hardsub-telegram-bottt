# Hardsub Telegram Bot

Burns subtitle files permanently into video (hardsub) via ffmpeg, supports
uploads/downloads up to 2GB. Runs entirely in Docker.

## Why it can handle 2GB

This bot uses **Pyrogram**, which talks to Telegram directly over MTProto
instead of the HTTP Bot API. The regular Bot API caps downloads at 20MB and
uploads at 50MB — Pyrogram bypasses that, so no local Bot API server is
needed for large files.

## 1. Get credentials

- `API_ID` and `API_HASH`: https://my.telegram.org → API Development Tools
- `BOT_TOKEN`: message @BotFather on Telegram → /newbot

## 2. Configure

Open `main.py` and edit the CONFIG block near the top:

```python
API_ID = 12345678
API_HASH = "your_api_hash_here"
BOT_TOKEN = "your_bot_token_here"
```

## 3. Build & run

```bash
docker compose up -d --build
```

Check logs:

```bash
docker compose logs -f
```

## 4. Use it

1. Open the bot on Telegram, send `/start`
2. Send a video file (up to 2GB)
3. Send the subtitle file (`.srt`, `.ass`, `.ssa`, or `.vtt`)
4. Wait — the bot burns the subs with ffmpeg (`libx264`, `crf 20`,
   `preset veryfast`) and uploads the result back to you
5. `/cancel` at any point to reset your session

## Notes

- Downloaded/output files are stored per-user under `downloads/<user_id>/`
  and are deleted automatically after the result is sent (or on `/cancel`).
- Session files persist in `sessions/` across container restarts, so the
  bot doesn't need to re-authenticate on every deploy.
- Encoding speed depends on your server's CPU — `veryfast`/`crf 20` is a
  balance of speed and quality; adjust in `main.py` (`run_hardsub`) if you
  want smaller files (higher crf) or faster/slower encodes.
- Only one video is tracked per user at a time. Sending a new video before
  finishing a previous job overwrites the pending one.

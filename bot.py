import os
import time
import math
import asyncio
import subprocess
import re
from pyrogram import Client, filters
from pyrogram.types import Message

API_ID = 36282056
API_HASH = "3a948acece533f362b4c90b2b3c14b60"
BOT_TOKEN = "8737705568:AAGSjZlCgT6yrs6h045X88EEq63-iZLCiD4"

app = Client("hardsub_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# In-memory user state tracker
USER_DATA = {}

# ---------------- PROGRESS BAR HELPER ----------------
def create_progress_bar(current, total, status_text, start_time):
    now = time.time()
    diff = now - start_time
    if diff == 0:
        return None

    percentage = current * 100 / total
    speed = current / diff  # bytes per second
    elapsed_time = round(diff)
    time_to_completion = round((total - current) / speed) if speed > 0 else 0

    progress = "[{0}{1}]".format(
        ''.join(["█" for _ in range(math.floor(percentage / 10))]),
        ''.join(["░" for _ in range(10 - math.floor(percentage / 10))])
    )
    
    speed_mb = speed / (1024 * 1024)
    downloaded_mb = current / (1024 * 1024)
    total_mb = total / (1024 * 1024)

    return (
        f"**{status_text}**\n"
        f"`{progress}` {percentage:.1f}%\n"
        f"⚡ **Speed:** {speed_mb:.2f} MB/s\n"
        f"📦 **Done:** {downloaded_mb:.1f} MB / {total_mb:.1f} MB\n"
        f"⏱️ **ETA:** {time_to_completion}s"
    )

# Throttled progress update to prevent Telegram API FloodWaits
class ProgressTracker:
    def __init__(self, message, action_title):
        self.message = message
        self.action_title = action_title
        self.last_update_time = 0
        self.start_time = time.time()

    async def callback(self, current, total):
        now = time.time()
        # Update UI every 2 seconds or when completed
        if now - self.last_update_time >= 2 or current == total:
            self.last_update_time = now
            text = create_progress_bar(current, total, self.action_title, self.start_time)
            if text:
                try:
                    await self.message.edit_text(text)
                except Exception:
                    pass

# ---------------- GET VIDEO DURATION ----------------
async def get_video_duration(video_path):
    cmd = [
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", video_path
    ]
    proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    stdout, _ = proc.communicate()
    try:
        return float(stdout.decode().strip())
    except Exception:
        return None

# ---------------- BOT HANDLERS ----------------

@app.on_message(filters.command("start"))
async def start_cmd(client: Client, message: Message):
    await message.reply_text(
        "⚡ **Ultra-Fast Hardsub Bot Active**\n\n"
        "1️⃣ Send me a subtitle file (`.srt` or `.ass`)\n"
        "2️⃣ Send me your video file (up to 2GB)"
    )

@app.on_message(filters.document & filters.private)
async def handle_document(client: Client, message: Message):
    filename = message.document.file_name or ""
    if filename.endswith((".srt", ".ass")):
        user_id = message.from_user.id
        status_msg = await message.reply_text("📥 Initializing subtitle download...")
        
        sub_path = f"sub_{user_id}_{filename}"
        tracker = ProgressTracker(status_msg, "📥 Downloading Subtitles")
        
        await message.download(file_name=sub_path, progress=tracker.callback)
        
        if user_id not in USER_DATA:
            USER_DATA[user_id] = {}
        USER_DATA[user_id]["sub"] = sub_path
        
        await status_msg.edit_text("✅ **Subtitle received!** Now send your video file.")
    else:
        await message.reply_text("⚠️ Please send a valid subtitle file (`.srt` or `.ass`).")

@app.on_message(filters.video & filters.private)
async def handle_video(client: Client, message: Message):
    user_id = message.from_user.id
    if user_id not in USER_DATA or "sub" not in USER_DATA[user_id]:
        await message.reply_text("⚠️ Please send a subtitle file first!")
        return

    sub_path = USER_DATA[user_id]["sub"]
    video_filename = message.video.file_name or "input.mp4"
    video_path = f"video_{user_id}_{video_filename}"
    output_path = f"hardsub_{user_id}.mp4"

    status_msg = await message.reply_text("📥 Starting high-speed download...")
    
    try:
        # 1. Download Video with Fast MTProto Progress
        dl_tracker = ProgressTracker(status_msg, "📥 Downloading Video")
        await message.download(file_name=video_path, progress=dl_tracker.callback)

        # 2. Extract Duration for FFmpeg Progress Calculation
        duration = await get_video_duration(video_path)

        # 3. Fast FFmpeg Burning with Real-Time Terminal Parsing
        await status_msg.edit_text("🔥 **Burning Subtitles (Ultra-Fast Engine)...**")
        
        # Escape single quotes in path for FFmpeg filter argument
        safe_sub_path = sub_path.replace("'", "'\\''")
        
        ffmpeg_cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-vf", f"subtitles='{safe_sub_path}'",
            "-c:a", "copy",              # Copy audio without re-encoding
            "-preset", "ultrafast",       # Ultra-fast encoding speed preset
            "-threads", "0",              # Maximize multi-core CPU threads usage
            output_path
        ]

        proc = await asyncio.create_subprocess_exec(
            *ffmpeg_cmd,
            stderr=asyncio.subprocess.PIPE
        )

        last_update = 0
        start_burn_time = time.time()
        time_pattern = re.compile(r"time=(\d+):(\d+):(\d+\.\d+)")

        # Read FFmpeg output line by line for burn progress calculation
        while True:
            line = await proc.stderr.readline()
            if not line:
                break
            line_str = line.decode('utf-8', errors='ignore')
            
            match = time_pattern.search(line_str)
            if match and duration:
                hours, minutes, seconds = map(float, match.groups())
                current_time = hours * 3600 + minutes * 60 + seconds
                
                now = time.time()
                if now - last_update >= 2.5:  # Rate-limit status updates
                    last_update = now
                    pct = min((current_time / duration) * 100, 100)
                    prog_bar = "[{0}{1}]".format(
                        ''.join(["█" for _ in range(math.floor(pct / 10))]),
                        ''.join(["░" for _ in range(10 - math.floor(pct / 10))])
                    )
                    
                    elapsed = now - start_burn_time
                    fps_estimate = current_time / elapsed if elapsed > 0 else 0
                    
                    try:
                        await status_msg.edit_text(
                            f"🔥 **Burning Subtitles into Video...**\n"
                            f"`{prog_bar}` {pct:.1f}%\n"
                            f"⏱️ **Processed:** {int(current_time)}s / {int(duration)}s\n"
                            f"⚡ **Speed Factor:** {fps_estimate:.1f}x"
                        )
                    except Exception:
                        pass

        await proc.wait()

        if proc.returncode != 0:
            await status_msg.edit_text("❌ FFmpeg encoding failed.")
            return

        # 4. Upload Processed Video
        ul_tracker = ProgressTracker(status_msg, "📤 Uploading Hardsubbed Video")
        await message.reply_video(
            video=output_path,
            caption="✅ **Hardsubbing completed successfully!**",
            progress=ul_tracker.callback
        )

    except Exception as e:
        await message.reply_text(f"❌ Error occurred: {str(e)}")
    
    finally:
        # Cleanup temp files
        for path in [sub_path, video_path, output_path]:
            if os.path.exists(path):
                os.remove(path)
        USER_DATA.pop(user_id, None)

if __name__ == "__main__":
    app.run()

import os
import asyncio
import subprocess
from pyrogram import Client, filters
from pyrogram.types import Message

# Fetch credentials from environment variables
API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")

app = Client("hardsub_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# Simple in-memory user tracking state
USER_DATA = {}

@app.on_message(filters.command("start"))
async def start_cmd(client: Client, message: Message):
    await message.reply_text(
        "👋 Welcome! Send me a **subtitle file** (.srt or .ass), and then send me the **video file**."
    )

@app.on_message(filters.document & filters.private)
async def handle_document(client: Client, message: Message):
    filename = message.document.file_name or ""
    if filename.endswith((".srt", ".ass")):
        user_id = message.from_user.id
        status_msg = await message.reply_text("📥 Downloading subtitle file...")
        
        sub_path = f"sub_{user_id}_{filename}"
        await message.download(file_name=sub_path)
        
        if user_id not in USER_DATA:
            USER_DATA[user_id] = {}
        USER_DATA[user_id]["sub"] = sub_path
        
        await status_msg.edit_text("✅ Subtitle received! Now send me the video file.")
    else:
        await message.reply_text("Please send a valid subtitle file (.srt or .ass).")

@app.on_message(filters.video & filters.private)
async def handle_video(client: Client, message: Message):
    user_id = message.from_user.id
    if user_id not in USER_DATA or "sub" not in USER_DATA[user_id]:
        await message.reply_text("⚠️ Please send a subtitle file first!")
        return

    sub_path = USER_DATA[user_id]["sub"]
    video_path = f"video_{user_id}_{message.video.file_name or 'input.mp4'}"
    output_path = f"hardsub_{user_id}.mp4"

    status_msg = await message.reply_text("📥 Downloading video... (This might take time for large files)")
    
    try:
        # Download video
        await message.download(file_name=video_path)
        
        await status_msg.edit_text("⚙️ Burning subtitles into video with FFmpeg...")
        
        # Build FFmpeg command (Escaping sub path for FFmpeg filter safety)
        safe_sub_path = sub_path.replace("'", "'\\''")
        ffmpeg_cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-vf", f"subtitles='{safe_sub_path}'",
            "-c:a", "copy",
            "-preset", "fast",
            output_path
        ]

        # Execute FFmpeg process asynchronously
        proc = await asyncio.create_subprocess_exec(*ffmpeg_cmd)
        await proc.communicate()

        if proc.returncode != 0:
            await status_msg.edit_text("❌ FFmpeg failed to process the video.")
            return

        await status_msg.edit_text("📤 Uploading processed video to Telegram...")
        
        # Progress callback for upload
        async def progress(current, total):
            percent = (current / total) * 100
            if int(percent) % 20 == 0:  # Update status periodically
                try:
                    await status_msg.edit_text(f"📤 Uploading: {percent:.1f}%")
                except Exception:
                    pass

        # Send back the hardsubbed video (up to 2GB native Pyrogram support)
        await message.reply_video(
            video=output_path,
            caption="✅ Hardsubbing completed!",
            progress=progress
        )

    except Exception as e:
        await message.reply_text(f"❌ An error occurred: {str(e)}")
    
    finally:
        # Clean up temporary files
        for f in [sub_path, video_path, output_path]:
            if os.path.exists(f):
                os.remove(f)
        USER_DATA.pop(user_id, None)

if __name__ == "__main__":
    app.run()

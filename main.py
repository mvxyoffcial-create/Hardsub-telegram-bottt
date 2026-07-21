import os
import time
import asyncio
from pyrogram import Client, filters, enums
from pyrogram.types import Message

# ==================== CONFIG ====================
# Get API_ID / API_HASH from https://my.telegram.org
# Get BOT_TOKEN from @BotFather
API_ID = 12345678
API_HASH = "your_api_hash_here"
BOT_TOKEN = "your_bot_token_here"

DOWNLOAD_DIR = "downloads"
# ==================================================

os.makedirs(DOWNLOAD_DIR, exist_ok=True)

app = Client(
    "hardsub_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    workdir="sessions",
)

# user_id -> {"video": path, "dir": path}
pending = {}

SUB_EXTS = (".srt", ".ass", ".ssa", ".vtt")


def human_size(n):
    for unit in ["B", "KB", "MB", "GB"]:
        if n < 1024:
            return f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}TB"


def cleanup(uid):
    info = pending.pop(uid, None)
    if info:
        try:
            for f in os.listdir(info["dir"]):
                os.remove(os.path.join(info["dir"], f))
            os.rmdir(info["dir"])
        except OSError:
            pass


@app.on_message(filters.command("start"))
async def start(_, message: Message):
    await message.reply_text(
        "**Hardsub Bot**\n\n"
        "1. Send me a video (up to 2GB)\n"
        "2. Then send the subtitle file (.srt / .ass / .ssa / .vtt)\n\n"
        "I'll burn the subtitles permanently into the video and send it back.\n"
        "Send /cancel anytime to reset."
    )


@app.on_message(filters.command("cancel"))
async def cancel(_, message: Message):
    uid = message.from_user.id
    cleanup(uid)
    await message.reply_text("Cancelled. You can send a new video.")


@app.on_message(filters.video | filters.document)
async def handle_file(client: Client, message: Message):
    uid = message.from_user.id
    doc = message.video or message.document

    is_video = message.video is not None or (
        message.document and (message.document.mime_type or "").startswith("video/")
    )
    is_sub = message.document and (message.document.file_name or "").lower().endswith(SUB_EXTS)

    if is_video:
        status = await message.reply_text("Downloading video... 0%")
        user_dir = os.path.join(DOWNLOAD_DIR, str(uid))
        os.makedirs(user_dir, exist_ok=True)
        ext = os.path.splitext(getattr(doc, "file_name", None) or "video.mp4")[1] or ".mp4"
        video_path = os.path.join(user_dir, f"input{ext}")

        last_edit = [0.0]

        async def dl_progress(current, total):
            now = time.time()
            if now - last_edit[0] > 3 or current == total:
                last_edit[0] = now
                pct = current * 100 / total if total else 0
                try:
                    await status.edit_text(
                        f"Downloading video... {pct:.0f}% ({human_size(current)}/{human_size(total)})"
                    )
                except Exception:
                    pass

        await message.download(file_name=video_path, progress=dl_progress)
        pending[uid] = {"video": video_path, "dir": user_dir}
        await status.edit_text("Video received.\nNow send the subtitle file (.srt/.ass/.ssa/.vtt).")
        return

    if is_sub:
        if uid not in pending:
            await message.reply_text("Send a video first, then the subtitle file.")
            return

        user_dir = pending[uid]["dir"]
        video_path = pending[uid]["video"]
        sub_ext = os.path.splitext(doc.file_name)[1]
        sub_path = os.path.join(user_dir, f"sub{sub_ext}")

        status = await message.reply_text("Downloading subtitle...")
        await message.download(file_name=sub_path)

        await status.edit_text("Burning subtitles into video... this can take a while for large files.")
        output_path = os.path.join(user_dir, "output.mp4")

        ok, err = await run_hardsub(video_path, sub_path, output_path, user_dir)
        if not ok:
            await status.edit_text(
                f"FFmpeg failed:\n{err[-1500:]}", parse_mode=enums.ParseMode.DISABLED
            )
            cleanup(uid)
            return

        await status.edit_text("Uploading hardsubbed video... 0%")

        last_edit = [0.0]

        async def up_progress(current, total):
            now = time.time()
            if now - last_edit[0] > 3 or current == total:
                last_edit[0] = now
                pct = current * 100 / total if total else 0
                try:
                    await status.edit_text(
                        f"Uploading... {pct:.0f}% ({human_size(current)}/{human_size(total)})"
                    )
                except Exception:
                    pass

        await client.send_video(
            chat_id=message.chat.id,
            video=output_path,
            caption="Hardsubbed ✅",
            progress=up_progress,
            supports_streaming=True,
        )
        await status.delete()
        cleanup(uid)
        return

    if message.document:
        await message.reply_text(
            "Unsupported file type. Send a video, or a .srt/.ass/.ssa/.vtt subtitle."
        )


async def run_hardsub(video_path, sub_path, output_path, workdir):
    """
    Runs ffmpeg from inside `workdir` using relative filenames only.
    This avoids subtitle-filter path-escaping issues that occur with
    absolute paths containing special characters (colons, spaces, etc).
    """
    video_name = os.path.basename(video_path)
    sub_name = os.path.basename(sub_path)
    out_name = os.path.basename(output_path)

    vf = f"subtitles={sub_name}"

    cmd = [
        "ffmpeg", "-y",
        "-i", video_name,
        "-vf", vf,
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-c:a", "copy",
        out_name,
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=workdir,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        return False, stderr.decode(errors="ignore")
    return True, ""


if __name__ == "__main__":
    print("Starting Hardsub Bot...")
    app.run()

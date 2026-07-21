import os
import re
import time
import asyncio
from pyrogram import Client, filters, enums
from pyrogram.types import Message

# ==================== CONFIG ====================
# Get API_ID / API_HASH from https://my.telegram.org
# Get BOT_TOKEN from @BotFather
API_ID = 36282056
API_HASH = "3a948acece533f362b4c90b2b3c14b60"
BOT_TOKEN = "8737705568:AAGSjZlCgT6yrs6h045X88EEq63-iZLCiD4"

DOWNLOAD_DIR = "downloads"

# How many chunks Pyrogram transfers in parallel for a single file.
# Higher = faster download/upload (up to your network/Telegram's limits).
# 4-8 is a good range; going too high can hit flood limits on weak links.
MAX_CONCURRENT_TRANSMISSIONS = 6

# ffmpeg encode speed. ultrafast = fastest burn, slightly larger file.
FFMPEG_PRESET = "ultrafast"
FFMPEG_CRF = "23"
# ==================================================

os.makedirs(DOWNLOAD_DIR, exist_ok=True)

app = Client(
    "hardsub_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    workdir="sessions",
    max_concurrent_transmissions=MAX_CONCURRENT_TRANSMISSIONS,
)

pending = {}
SUB_EXTS = (".srt", ".ass", ".ssa", ".vtt")
EDIT_INTERVAL = 2.5


def human_size(n):
    for unit in ["B", "KB", "MB", "GB"]:
        if n < 1024:
            return f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}TB"


def human_time(seconds):
    if seconds is None or seconds == float("inf") or seconds < 0:
        return "--"
    seconds = int(seconds)
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}h{m:02d}m"
    if m:
        return f"{m}m{s:02d}s"
    return f"{s}s"


def bar(pct, width=14):
    pct = max(0, min(100, pct))
    filled = int(width * pct / 100)
    return "▓" * filled + "░" * (width - filled)


def cleanup(uid):
    info = pending.pop(uid, None)
    if info:
        try:
            for f in os.listdir(info["dir"]):
                os.remove(os.path.join(info["dir"], f))
            os.rmdir(info["dir"])
        except OSError:
            pass


class ProgressTracker:
    """Shared helper for download/upload progress bars with speed + ETA."""

    def __init__(self, status_msg, label):
        self.status_msg = status_msg
        self.label = label
        self.start = time.time()
        self.last_edit = 0.0

    async def __call__(self, current, total):
        now = time.time()
        if now - self.last_edit < EDIT_INTERVAL and current != total:
            return
        self.last_edit = now

        elapsed = max(now - self.start, 0.001)
        speed = current / elapsed
        pct = (current * 100 / total) if total else 0
        eta = (total - current) / speed if speed > 0 else None

        text = (
            f"{self.label}\n"
            f"[{bar(pct)}] {pct:.1f}%\n"
            f"{human_size(current)} / {human_size(total)}  •  "
            f"{human_size(speed)}/s  •  ETA {human_time(eta)}"
        )
        try:
            await self.status_msg.edit_text(text)
        except Exception:
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
        status = await message.reply_text("Starting download...")
        user_dir = os.path.join(DOWNLOAD_DIR, str(uid))
        os.makedirs(user_dir, exist_ok=True)
        ext = os.path.splitext(getattr(doc, "file_name", None) or "video.mp4")[1] or ".mp4"
        video_path = os.path.join(user_dir, f"input{ext}")

        tracker = ProgressTracker(status, "⬇️ Downloading video")
        await message.download(file_name=video_path, progress=tracker)

        pending[uid] = {"video": video_path, "dir": user_dir}
        await status.edit_text("✅ Video received.\nNow send the subtitle file (.srt/.ass/.ssa/.vtt).")
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

        output_path = os.path.join(user_dir, "output.mp4")

        ok, err = await run_hardsub(video_path, sub_path, output_path, user_dir, status)
        if not ok:
            preview = err[:700] + "\n...\n" + err[-700:] if len(err) > 1500 else err
            await status.edit_text(
                f"FFmpeg failed:\n{preview}", parse_mode=enums.ParseMode.DISABLED
            )
            cleanup(uid)
            return

        tracker = ProgressTracker(status, "⬆️ Uploading hardsubbed video")
        await client.send_video(
            chat_id=message.chat.id,
            video=output_path,
            caption="Hardsubbed ✅",
            progress=tracker,
            supports_streaming=True,
        )
        await status.delete()
        cleanup(uid)
        return

    if message.document:
        await message.reply_text(
            "Unsupported file type. Send a video, or a .srt/.ass/.ssa/.vtt subtitle."
        )


async def get_duration_seconds(path, workdir):
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        os.path.basename(path),
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd, cwd=workdir,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, _ = await proc.communicate()
    try:
        return float(out.decode().strip())
    except ValueError:
        return None


TIME_RE = re.compile(rb"out_time_ms=(\d+)")
SPEED_RE = re.compile(rb"speed=\s*([\d.]+)x")


async def run_hardsub(video_path, sub_path, output_path, workdir, status_msg):
    video_name = os.path.basename(video_path)
    sub_name = os.path.basename(sub_path)
    out_name = os.path.basename(output_path)

    duration = await get_duration_seconds(video_path, workdir)
    vf = f"subtitles={sub_name}"

    cmd = [
        "ffmpeg", "-y",
        "-i", video_name,
        "-vf", vf,
        "-c:v", "libx264",
        "-preset", FFMPEG_PRESET,
        "-crf", FFMPEG_CRF,
        "-threads", "0",
        "-c:a", "copy",
        "-progress", "pipe:1",
        "-nostats",
        out_name,
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd, cwd=workdir,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    stderr_chunks = []
    start = time.time()
    last_edit = 0.0
    last_pct = 0.0

    async def read_stderr():
        while True:
            line = await proc.stderr.readline()
            if not line:
                break
            stderr_chunks.append(line)

    stderr_task = asyncio.create_task(read_stderr())

    while True:
        line = await proc.stdout.readline()
        if not line:
            break

        now = time.time()
        m = TIME_RE.search(line)
        if m and duration:
            out_time_s = int(m.group(1)) / 1_000_000
            last_pct = min(100.0, out_time_s / duration * 100)

        sm = SPEED_RE.search(line)
        enc_speed = sm.group(1).decode() if sm else "?"

        if now - last_edit > EDIT_INTERVAL:
            last_edit = now
            elapsed = now - start
            eta = elapsed * (100 - last_pct) / last_pct if last_pct > 0 else None
            text = (
                f"🔥 Burning subtitles\n"
                f"[{bar(last_pct)}] {last_pct:.1f}%\n"
                f"encode speed {enc_speed}x  •  ETA {human_time(eta)}"
            )
            try:
                await status_msg.edit_text(text)
            except Exception:
                pass

    await stderr_task
    returncode = await proc.wait()

    if returncode != 0:
        return False, b"".join(stderr_chunks).decode(errors="ignore")

    try:
        await status_msg.edit_text(f"🔥 Burning subtitles\n[{bar(100)}] 100%\nDone.")
    except Exception:
        pass

    return True, ""


if __name__ == "__main__":
    print("Starting Hardsub Bot...")
    app.run()

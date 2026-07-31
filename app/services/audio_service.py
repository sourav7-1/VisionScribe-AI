import asyncio
import shutil
import uuid
from pathlib import Path

from app.config import Settings
from app.utils.errors import AppError


async def extract_audio(video_path: Path, settings: Settings) -> Path:
    binary = settings.ffmpeg_binary
    resolved = binary if Path(binary).exists() else shutil.which(binary)
    if not resolved:
        raise AppError("ffmpeg_unavailable", "FFmpeg is unavailable on this server.", 503)
    settings.temp_dir.mkdir(parents=True, exist_ok=True)
    audio_path = settings.temp_dir / f"{uuid.uuid4().hex}.{settings.audio_format}"
    try:
        process = await asyncio.create_subprocess_exec(
            resolved,
            "-nostdin",
            "-v",
            "error",
            "-i",
            str(video_path),
            "-vn",
            "-ac",
            str(settings.audio_channels),
            "-ar",
            str(settings.audio_sample_rate),
            "-c:a",
            "pcm_s16le",
            "-y",
            str(audio_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(
            process.communicate(), timeout=settings.audio_extraction_timeout_seconds
        )
    except TimeoutError as exc:
        audio_path.unlink(missing_ok=True)
        raise AppError("audio_extraction_timeout", "Audio extraction timed out.") from exc
    except OSError as exc:
        audio_path.unlink(missing_ok=True)
        raise AppError("audio_extraction_failed", "Audio could not be extracted.") from exc
    if process.returncode != 0 or not audio_path.exists() or audio_path.stat().st_size <= 44:
        audio_path.unlink(missing_ok=True)
        message = "No usable audio could be extracted from this video."
        if stderr:
            raise AppError("audio_extraction_failed", message)
        raise AppError("empty_audio", message)
    return audio_path

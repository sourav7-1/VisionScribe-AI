import asyncio
import json
import logging
import mimetypes
import os
import shutil
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import httpx

from app.config import Settings
from app.utils.errors import AppError
from app.utils.url_safety import validate_public_url

logger = logging.getLogger(__name__)
SUPPORTED_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}
SUPPORTED_MIME_TYPES = {
    "video/mp4", "video/quicktime", "video/x-matroska", "video/webm",
    "video/x-msvideo", "video/avi", "application/octet-stream",
}


def sanitize_filename(filename: str | None) -> str:
    name = Path(filename or "video").name
    cleaned = "".join(ch for ch in name if ch.isalnum() or ch in "._- ").strip(" .")
    return (cleaned or "video")[:255]


def validate_upload_headers(filename: str, content_type: str | None) -> None:
    if Path(filename).suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise AppError("unsupported_video_format", "The uploaded video format is not supported.")
    normalized = (content_type or "").split(";", 1)[0].lower()
    if normalized not in SUPPORTED_MIME_TYPES:
        raise AppError("unsupported_mime_type", "The uploaded file MIME type is not supported.")


async def probe_video(path: Path, settings: Settings) -> dict:
    binary = settings.ffprobe_binary
    resolved = shutil.which(binary) if not Path(binary).exists() else binary
    if not resolved:
        raise AppError("ffprobe_unavailable", "FFprobe is unavailable on this server.", 503)
    try:
        process = await asyncio.create_subprocess_exec(
            resolved, "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(
            process.communicate(), timeout=settings.request_timeout_seconds
        )
    except (OSError, TimeoutError) as exc:
        raise AppError("ffprobe_unavailable", "FFprobe could not inspect the video.", 503) from exc
    if process.returncode != 0:
        raise AppError("corrupted_video", "The video is corrupted or unreadable.")
    try:
        data = json.loads(stdout)
        streams = data.get("streams", [])
        video = next((s for s in streams if s.get("codec_type") == "video"), None)
        audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
        duration = float(data.get("format", {}).get("duration") or video.get("duration"))
    except (TypeError, ValueError, AttributeError, json.JSONDecodeError) as exc:
        raise AppError("corrupted_video", "The video metadata is invalid.") from exc
    if not video:
        raise AppError("missing_video_stream", "The file does not contain a video stream.")
    if duration <= 0:
        raise AppError("corrupted_video", "The video has an invalid duration.")
    if duration > settings.max_video_duration_seconds:
        raise AppError("video_too_long", "The video exceeds the configured duration limit.")
    return {
        "duration": duration,
        "video_codec": video.get("codec_name"),
        "audio_codec": audio.get("codec_name") if audio else None,
        "has_audio": audio is not None,
        "width": video.get("width"),
        "height": video.get("height"),
    }


async def download_public_video(url: str, target: Path, settings: Settings) -> None:
    current = url
    timeout = httpx.Timeout(settings.url_download_timeout_seconds)
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
            for redirect_count in range(settings.max_url_redirects + 1):
                await validate_public_url(current)
                async with client.stream("GET", current, headers={"Accept": "video/*"}) as response:
                    if response.status_code in {301, 302, 303, 307, 308}:
                        location = response.headers.get("location")
                        if not location:
                            raise AppError(
                                "unreachable_url", "The video URL returned an invalid redirect."
                            )
                        if redirect_count >= settings.max_url_redirects:
                            raise AppError(
                                "too_many_redirects", "The video URL has too many redirects."
                            )
                        current = urljoin(current, location)
                        continue
                    if response.status_code in {401, 403}:
                        raise AppError(
                            "authentication_restricted_url",
                            "This URL is restricted. Upload an authorized local video instead.",
                        )
                    if response.status_code >= 400:
                        raise AppError(
                            "unreachable_url", "The public video URL could not be downloaded."
                        )
                    content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
                    suffix = Path(urlsplit(current).path).suffix.lower()
                    guessed = mimetypes.guess_type(current)[0]
                    if content_type and not content_type.startswith("video/") and (
                        content_type != "application/octet-stream"
                        or suffix not in SUPPORTED_EXTENSIONS
                    ):
                        raise AppError("url_not_video", "The URL did not return a supported video.")
                    if guessed and not guessed.startswith("video/") and suffix:
                        raise AppError("url_not_video", "The URL does not point to a video.")
                    total = 0
                    with target.open("wb") as output:
                        async for chunk in response.aiter_bytes(settings.upload_chunk_size_bytes):
                            total += len(chunk)
                            if total > settings.max_upload_size_mb * 1024 * 1024:
                                raise AppError(
                                    "file_too_large", "The video exceeds the upload size limit."
                                )
                            output.write(chunk)
                    if total == 0:
                        raise AppError("empty_file", "The downloaded video is empty.")
                    return
    except httpx.TimeoutException as exc:
        raise AppError("download_timeout", "The video download timed out.") from exc
    except httpx.RequestError as exc:
        raise AppError("unreachable_url", "The public video URL could not be reached.") from exc
    finally:
        if target.exists() and target.stat().st_size == 0:
            os.unlink(target)

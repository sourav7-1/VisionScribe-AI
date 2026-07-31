import json
import math
import re
from dataclasses import dataclass

from app.models.processing_job import ProcessingJob
from app.utils.errors import AppError
from app.utils.timestamp import format_srt_timestamp, format_timestamp

LANGUAGE_NAMES = {"bn": "Bengali", "en": "English"}


@dataclass(frozen=True)
class TranscriptExport:
    content: str
    media_type: str
    filename: str


def _segments(job: ProcessingJob) -> list[dict]:
    if job.transcription_status != "completed":
        raise AppError(
            "transcript_unavailable",
            "A completed transcription is required before downloading a transcript.",
            409,
        )
    if not job.transcript_json:
        raise AppError("empty_transcript", "No transcript segments are available.", 409)
    return job.transcript_json


def _safe_stem(job: ProcessingJob) -> str:
    raw = (job.original_filename or "visionscribe-transcript").rsplit(".", 1)[0]
    stem = re.sub(r"[^A-Za-z0-9_-]+", "-", raw).strip("-_")[:80]
    return stem or "visionscribe-transcript"


def _filename(job: ProcessingJob, extension: str) -> str:
    short_id = re.sub(r"[^A-Za-z0-9]", "", job.id)[:8] or "transcript"
    return f"{_safe_stem(job)}-{short_id}.{extension}"


def _language(job: ProcessingJob) -> str:
    code = job.detected_language or "Unknown"
    return LANGUAGE_NAMES.get(code, code.upper() if code != "Unknown" else code)


def _validated_times(segment: dict) -> tuple[float, float]:
    try:
        start = float(segment.get("start", 0))
        end = float(segment.get("end", start))
    except (TypeError, ValueError) as exc:
        raise AppError("invalid_transcript", "A transcript timestamp is invalid.", 409) from exc
    if not math.isfinite(start) or not math.isfinite(end) or start < 0 or end < start:
        raise AppError("invalid_transcript", "A transcript timestamp range is invalid.", 409)
    return start, end


def export_txt(job: ProcessingJob) -> TranscriptExport:
    lines = [
        "VisionScribe AI Transcript",
        "Identity: Unknown",
        f"Detected language: {_language(job)}",
        f"Video duration: {format_timestamp(job.video_duration or 0)}",
        "",
    ]
    for segment in _segments(job):
        start, _ = _validated_times(segment)
        text = str(segment.get("text", "")).strip()
        lines.append(f"{format_timestamp(start)} — Person 1: {text}")
    return TranscriptExport(
        "\n".join(lines) + "\n", "text/plain; charset=utf-8", _filename(job, "txt")
    )


def export_json(job: ProcessingJob) -> TranscriptExport:
    segments = []
    for index, segment in enumerate(_segments(job), start=1):
        start, end = _validated_times(segment)
        segments.append(
            {
                "id": segment.get("id", index),
                "start": start,
                "end": end,
                "speaker": "Person 1",
                "text": str(segment.get("text", "")),
            }
        )
    payload = {
        "job_id": job.id,
        "identity": "Unknown",
        "face_detected": job.face_detected,
        "maximum_face_count": job.maximum_face_count,
        "sampled_frame_count": job.sampled_frame_count,
        "average_detection_confidence": job.average_detection_confidence,
        "best_detection_confidence": job.best_detection_confidence,
        "detected_language": job.detected_language,
        "language_probability": job.language_probability,
        "video_duration": job.video_duration,
        "transcription_status": job.transcription_status,
        "segments": segments,
    }
    return TranscriptExport(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        "application/json; charset=utf-8",
        _filename(job, "json"),
    )


def export_srt(job: ProcessingJob) -> TranscriptExport:
    blocks = []
    for index, segment in enumerate(_segments(job), start=1):
        start, end = _validated_times(segment)
        text = str(segment.get("text", "")).strip().replace("\r\n", "\n").replace("\r", "\n")
        blocks.append(
            f"{index}\n{format_srt_timestamp(start)} --> {format_srt_timestamp(end)}\n{text}"
        )
    return TranscriptExport(
        "\n\n".join(blocks) + "\n",
        "application/x-subrip; charset=utf-8",
        _filename(job, "srt"),
    )

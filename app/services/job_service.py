import asyncio
import logging
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import SessionLocal
from app.models.processing_job import JobStatus, ProcessingJob
from app.services.audio_service import extract_audio
from app.services.face_detection_service import detect_faces_in_video
from app.services.transcription_service import transcribe_audio
from app.services.video_service import download_public_video, probe_video
from app.utils.errors import AppError

logger = logging.getLogger(__name__)
COMPLETE_STAGE = "Processing complete — face detection and transcription finished"
SKIPPED_STAGE = "Face detection complete — transcription skipped by configuration"
NO_AUDIO_STAGE = "Face detection complete — transcription unavailable because no audio was found"


def create_job(
    db: Session,
    source_type: str,
    original_filename: str | None = None,
    source_url: str | None = None,
) -> ProcessingJob:
    job = ProcessingJob(
        source_type=source_type,
        original_filename=original_filename,
        source_url=source_url,
        status=JobStatus.queued.value,
        progress=5,
        current_stage="Queued",
        transcription_status="pending",
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def update_job(db: Session, job: ProcessingJob, **values: object) -> None:
    for key, value in values.items():
        setattr(job, key, value)
    db.commit()


def report_job_progress(job_id: str, progress: int, stage: str) -> None:
    with SessionLocal() as db:
        job = db.get(ProcessingJob, job_id)
        if job and progress >= job.progress:
            update_job(db, job, progress=progress, current_stage=stage)


def save_face_result(db: Session, job: ProcessingJob, result: object, duration: float) -> None:
    update_job(
        db,
        job,
        video_duration=duration,
        face_detected=result.face_detected,
        maximum_face_count=result.maximum_face_count,
        sampled_frame_count=result.sampled_frame_count,
        average_detection_confidence=result.average_detection_confidence,
        best_detection_confidence=result.best_detection_confidence,
        inference_device=result.inference_device,
    )


def complete_without_transcription(
    db: Session, job: ProcessingJob, transcription_status: str, stage: str, warning: str
) -> None:
    update_job(
        db,
        job,
        status=JobStatus.completed.value,
        progress=100,
        current_stage=stage,
        transcription_status=transcription_status,
        transcription_warning=warning,
        transcript_json=[],
        transcription_segment_count=0,
        completed_at=datetime.now(UTC),
        error_message=None,
    )


async def process_job(job_id: str, temp_path: Path | None) -> None:
    settings = get_settings()
    db = SessionLocal()
    audio_path: Path | None = None
    try:
        job = db.get(ProcessingJob, job_id)
        if not job:
            return
        update_job(
            db,
            job,
            status=JobStatus.processing.value,
            progress=15,
            current_stage="Obtaining video",
        )
        path = temp_path or settings.temp_dir / f"{job.id}.download"
        if job.source_type == "url":
            await download_public_video(job.source_url or "", path, settings)
        update_job(db, job, progress=25, current_stage="Reading video metadata")
        metadata = await probe_video(path, settings)
        face_result = await asyncio.to_thread(
            detect_faces_in_video,
            path,
            metadata["duration"],
            settings,
            lambda progress, stage: report_job_progress(job_id, progress, stage),
        )
        db.refresh(job)
        save_face_result(db, job, face_result, metadata["duration"])

        if not face_result.face_detected and not settings.transcribe_without_face:
            complete_without_transcription(
                db,
                job,
                "skipped",
                SKIPPED_STAGE,
                "Transcription was skipped because no human face was detected "
                "and configuration disables it.",
            )
            return
        if not metadata.get("has_audio", True):
            complete_without_transcription(
                db,
                job,
                "unavailable",
                NO_AUDIO_STAGE,
                "No audio stream was found in this video.",
            )
            return

        try:
            update_job(
                db,
                job,
                progress=60,
                current_stage="Extracting audio",
                transcription_status="processing",
            )
            audio_path = await extract_audio(path, settings)
            update_job(db, job, progress=70, current_stage="Loading transcription model")
            transcription = await asyncio.to_thread(transcribe_audio, audio_path, settings)
            update_job(db, job, progress=98, current_stage="Saving transcript")
            update_job(
                db,
                job,
                status=JobStatus.completed.value,
                progress=100,
                current_stage=COMPLETE_STAGE,
                transcription_status="completed",
                transcription_device=transcription.device,
                detected_language=transcription.language,
                language_probability=transcription.language_probability,
                audio_duration=transcription.audio_duration,
                transcript_json=transcription.segments,
                transcription_segment_count=len(transcription.segments),
                transcription_warning=None,
                completed_at=datetime.now(UTC),
                error_message=None,
            )
        except AppError as exc:
            logger.warning("Job %s transcription failed with %s", job_id, exc.code)
            update_job(
                db,
                job,
                status=JobStatus.completed.value,
                progress=100,
                current_stage="Face detection complete — transcription failed",
                transcription_status="failed",
                transcription_warning=exc.message,
                transcript_json=[],
                transcription_segment_count=0,
                completed_at=datetime.now(UTC),
                error_message=None,
            )
    except AppError as exc:
        logger.warning("Job %s failed with %s", job_id, exc.code)
        job = db.get(ProcessingJob, job_id)
        if job:
            update_job(
                db,
                job,
                status=JobStatus.failed.value,
                progress=100,
                current_stage="Processing failed",
                error_message=exc.message,
                completed_at=datetime.now(UTC),
            )
    except Exception:
        logger.exception("Unexpected processing failure for job %s", job_id)
        job = db.get(ProcessingJob, job_id)
        if job:
            update_job(
                db,
                job,
                status=JobStatus.failed.value,
                progress=100,
                current_stage="Processing failed",
                error_message="The video could not be processed safely.",
                completed_at=datetime.now(UTC),
            )
    finally:
        db.close()
        if audio_path:
            audio_path.unlink(missing_ok=True)
        if temp_path:
            temp_path.unlink(missing_ok=True)
        else:
            (settings.temp_dir / f"{job_id}.download").unlink(missing_ok=True)

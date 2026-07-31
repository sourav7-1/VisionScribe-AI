import logging
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import SessionLocal
from app.models.processing_job import JobStatus, ProcessingJob
from app.services.video_service import download_public_video, probe_video
from app.utils.errors import AppError

logger = logging.getLogger(__name__)
COMPLETE_STAGE = "Ingestion complete — ready for face detection in Phase 3"


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
        current_stage="Queued for validation",
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def update_job(db: Session, job: ProcessingJob, **values: object) -> None:
    for key, value in values.items():
        setattr(job, key, value)
    db.commit()


async def process_job(job_id: str, temp_path: Path | None) -> None:
    settings = get_settings()
    db = SessionLocal()
    try:
        job = db.get(ProcessingJob, job_id)
        if not job:
            return
        update_job(
            db, job, status=JobStatus.processing.value, progress=15,
            current_stage="Downloading public video safely"
            if job.source_type == "url" else "Preparing uploaded video",
        )
        path = temp_path or settings.temp_dir / f"{job.id}.download"
        if job.source_type == "url":
            await download_public_video(job.source_url or "", path, settings)
        update_job(db, job, progress=45, current_stage="Inspecting video metadata")
        metadata = await probe_video(path, settings)
        update_job(
            db, job, status=JobStatus.completed.value, progress=100,
            current_stage=COMPLETE_STAGE, video_duration=metadata["duration"],
            completed_at=datetime.now(UTC), error_message=None,
        )
    except AppError as exc:
        logger.warning("Job %s failed with %s", job_id, exc.code)
        job = db.get(ProcessingJob, job_id)
        if job:
            update_job(
                db, job, status=JobStatus.failed.value, progress=100,
                current_stage="Ingestion failed", error_message=exc.message,
                completed_at=datetime.now(UTC),
            )
    except Exception:
        logger.exception("Unexpected ingestion failure for job %s", job_id)
        job = db.get(ProcessingJob, job_id)
        if job:
            update_job(
                db, job, status=JobStatus.failed.value, progress=100,
                current_stage="Ingestion failed",
                error_message="The video could not be processed safely.",
                completed_at=datetime.now(UTC),
            )
    finally:
        db.close()
        if temp_path:
            temp_path.unlink(missing_ok=True)
        else:
            (settings.temp_dir / f"{job_id}.download").unlink(missing_ok=True)

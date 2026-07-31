import uuid
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, File, UploadFile, status
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.models.processing_job import ProcessingJob
from app.schemas.job import JobAccepted, JobResponse, URLJobRequest
from app.services.job_service import create_job, process_job
from app.services.video_service import sanitize_filename, validate_upload_headers
from app.utils.errors import AppError, http_error
from app.utils.url_safety import validate_public_url

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.post("/upload", response_model=JobAccepted, status_code=status.HTTP_202_ACCEPTED)
async def upload_video(
    background_tasks: BackgroundTasks,
    video: Annotated[UploadFile, File()],
    db: Annotated[Session, Depends(get_db)],
) -> JobAccepted:
    settings = get_settings()
    filename = sanitize_filename(video.filename)
    try:
        validate_upload_headers(filename, video.content_type)
        settings.temp_dir.mkdir(parents=True, exist_ok=True)
        temp_path = settings.temp_dir / f"{uuid.uuid4().hex}{Path(filename).suffix.lower()}"
        total = 0
        with temp_path.open("wb") as output:
            while chunk := await video.read(settings.upload_chunk_size_bytes):
                total += len(chunk)
                if total > settings.max_upload_size_mb * 1024 * 1024:
                    raise AppError(
                        "file_too_large", "The uploaded video exceeds the size limit.", 413
                    )
                output.write(chunk)
        if total == 0:
            raise AppError("empty_file", "The uploaded video is empty.")
        job = create_job(db, "upload", original_filename=filename)
        background_tasks.add_task(process_job, job.id, temp_path)
        return JobAccepted(job_id=job.id, status=job.status, poll_url=f"/api/jobs/{job.id}")
    except AppError as exc:
        if "temp_path" in locals():
            temp_path.unlink(missing_ok=True)
        raise http_error(exc) from exc
    finally:
        await video.close()


@router.post("/url", response_model=JobAccepted, status_code=status.HTTP_202_ACCEPTED)
async def public_url(
    payload: URLJobRequest,
    background_tasks: BackgroundTasks,
    db: Annotated[Session, Depends(get_db)],
) -> JobAccepted:
    url = str(payload.url)
    try:
        await validate_public_url(url)
    except AppError as exc:
        raise http_error(exc) from exc
    job = create_job(db, "url", source_url=url)
    background_tasks.add_task(process_job, job.id, None)
    return JobAccepted(job_id=job.id, status=job.status, poll_url=f"/api/jobs/{job.id}")


@router.get("/{job_id}", response_model=JobResponse)
def get_job(job_id: str, db: Annotated[Session, Depends(get_db)]) -> JobResponse:
    job = db.get(ProcessingJob, job_id)
    if not job:
        error = AppError("unknown_job", "The requested processing job was not found.", 404)
        raise http_error(error)
    return JobResponse(
        job_id=job.id,
        source_type=job.source_type,
        original_filename=job.original_filename,
        source_url=job.source_url,
        status=job.status,
        progress=job.progress,
        current_stage=job.current_stage,
        video_duration=job.video_duration,
        face_detected=job.face_detected,
        maximum_face_count=job.maximum_face_count,
        sampled_frame_count=job.sampled_frame_count,
        average_detection_confidence=job.average_detection_confidence,
        best_detection_confidence=job.best_detection_confidence,
        detected_language=job.detected_language,
        error_message=job.error_message,
        created_at=job.created_at,
        completed_at=job.completed_at,
    )

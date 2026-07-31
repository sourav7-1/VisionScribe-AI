from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.processing_job import ProcessingJob
from app.services.transcript_export_service import export_json, export_srt, export_txt
from app.utils.errors import AppError, http_error

router = APIRouter(prefix="/api/jobs", tags=["transcripts"])
EXPORTERS = {"txt": export_txt, "json": export_json, "srt": export_srt}


@router.get("/{job_id}/transcript.{extension}")
def download_transcript(
    job_id: str,
    extension: Literal["txt", "json", "srt"],
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    job = db.get(ProcessingJob, job_id)
    if not job:
        error = AppError("unknown_job", "The requested processing job was not found.", 404)
        raise http_error(error)
    try:
        result = EXPORTERS[extension](job)
    except AppError as exc:
        raise http_error(exc) from exc
    return Response(
        content=result.content.encode("utf-8"),
        media_type=result.media_type,
        headers={"Content-Disposition": f'attachment; filename="{result.filename}"'},
    )

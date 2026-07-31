from datetime import datetime

from pydantic import BaseModel, ConfigDict, HttpUrl


class URLJobRequest(BaseModel):
    url: HttpUrl


class JobAccepted(BaseModel):
    job_id: str
    status: str
    poll_url: str


class JobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    job_id: str
    source_type: str
    original_filename: str | None
    source_url: str | None
    status: str
    progress: int
    current_stage: str
    video_duration: float | None
    face_detected: bool | None
    maximum_face_count: int | None
    sampled_frame_count: int | None
    average_detection_confidence: float | None
    best_detection_confidence: float | None
    detected_language: str | None
    error_message: str | None
    created_at: datetime
    completed_at: datetime | None


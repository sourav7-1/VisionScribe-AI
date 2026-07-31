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

    id: str
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
    inference_device: str | None
    detected_language: str | None
    transcript_json: list[dict] | None
    transcription_status: str | None
    transcription_device: str | None
    language_probability: float | None
    audio_duration: float | None
    transcription_segment_count: int | None
    transcription_warning: str | None
    error_message: str | None
    created_at: datetime
    completed_at: datetime | None

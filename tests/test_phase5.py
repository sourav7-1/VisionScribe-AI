import pytest
from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.models.processing_job import ProcessingJob
from app.services.job_service import create_job
from app.services.transcript_export_service import export_srt
from app.utils.errors import AppError
from app.utils.timestamp import format_srt_timestamp

BENGALI = "সবাইকে স্বাগতম।"


@pytest.fixture
def client() -> TestClient:
    with TestClient(app) as value:
        yield value


def completed_job(*, segments: list[dict] | None = None, filename: str = "video.mp4") -> str:
    with SessionLocal() as db:
        job = create_job(db, "upload", filename)
        job.status = "completed"
        job.transcription_status = "completed"
        job.face_detected = True
        job.maximum_face_count = 1
        job.sampled_frame_count = 42
        job.average_detection_confidence = 0.88
        job.best_detection_confidence = 0.96
        job.detected_language = "bn"
        job.language_probability = 0.94
        job.video_duration = 45.2
        job.transcript_json = segments if segments is not None else [
            {"id": 1, "start": 3.12, "end": 8.75, "speaker": "Person 1", "text": BENGALI},
            {"id": 2, "start": 9.04, "end": 15.62, "speaker": "Person 1", "text": "My project"},
        ]
        job.transcription_segment_count = len(job.transcript_json)
        db.commit()
        return job.id


@pytest.mark.parametrize(
    ("extension", "content_type"),
    [("txt", "text/plain"), ("json", "application/json"), ("srt", "application/x-subrip")],
)
def test_export_success_headers_and_safe_filename(
    client: TestClient, extension: str, content_type: str
) -> None:
    job_id = completed_job(filename="../../bad-name.mp4")
    response = client.get(f"/api/jobs/{job_id}/transcript.{extension}")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith(content_type)
    disposition = response.headers["content-disposition"]
    assert disposition.startswith('attachment; filename="')
    assert ".." not in disposition and "\r" not in disposition and "\n" not in disposition
    assert job_id[:8] in disposition


def test_txt_export_unicode_identity_and_timestamps(client: TestClient) -> None:
    response = client.get(f"/api/jobs/{completed_job()}/transcript.txt")
    assert BENGALI in response.text
    assert "Identity: Unknown" in response.text
    assert "Detected language: Bengali" in response.text
    assert "00:03 — Person 1" in response.text
    assert "Video duration: 00:45" in response.text


def test_json_export_unicode_identity_and_privacy(client: TestClient) -> None:
    job_id = completed_job()
    with SessionLocal() as db:
        job = db.get(ProcessingJob, job_id)
        job.source_url = "https://secret.example/video.mp4"
        db.commit()
    response = client.get(f"/api/jobs/{job_id}/transcript.json")
    payload = response.json()
    assert BENGALI in response.text and "\\u09" not in response.text
    assert payload["identity"] == "Unknown"
    assert payload["segments"][0]["speaker"] == "Person 1"
    assert "source_url" not in payload and "temp" not in response.text.lower()


def test_srt_export_unicode_numbering_and_timestamps(client: TestClient) -> None:
    response = client.get(f"/api/jobs/{completed_job()}/transcript.srt")
    assert response.text.startswith("1\n00:00:03,120 --> 00:00:08,750")
    assert "\n\n2\n00:00:09,040 --> 00:00:15,620" in response.text
    assert BENGALI in response.text and "Person 1:" not in response.text


@pytest.mark.parametrize("extension", ["txt", "json", "srt"])
def test_unknown_job_export_is_structured_404(client: TestClient, extension: str) -> None:
    response = client.get(f"/api/jobs/not-a-job/transcript.{extension}")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "unknown_job"


@pytest.mark.parametrize(
    ("status", "segments", "code"),
    [
        ("pending", None, "transcript_unavailable"),
        ("failed", [], "transcript_unavailable"),
        ("completed", [], "empty_transcript"),
    ],
)
def test_unavailable_export_rejection(
    client: TestClient, status: str, segments: list[dict] | None, code: str
) -> None:
    job_id = completed_job()
    with SessionLocal() as db:
        job = db.get(ProcessingJob, job_id)
        job.transcription_status = status
        job.transcript_json = segments
        db.commit()
    response = client.get(f"/api/jobs/{job_id}/transcript.txt")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == code


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        (0, "00:00:00,000"),
        (0.999, "00:00:00,999"),
        (59.999, "00:00:59,999"),
        (60, "00:01:00,000"),
        (3599.999, "00:59:59,999"),
        (3600, "01:00:00,000"),
    ],
)
def test_srt_millisecond_rounding(seconds: float, expected: str) -> None:
    assert format_srt_timestamp(seconds) == expected


def test_negative_srt_timestamp_rejected() -> None:
    with pytest.raises(ValueError):
        format_srt_timestamp(-0.1)


@pytest.mark.parametrize(
    "segment",
    [
        {"start": -1, "end": 1, "text": "bad"},
        {"start": 2, "end": 1, "text": "bad"},
        {"start": float("inf"), "end": float("inf"), "text": "bad"},
    ],
)
def test_invalid_srt_range_rejected(segment: dict) -> None:
    job_id = completed_job(segments=[segment])
    with SessionLocal() as db:
        with pytest.raises(AppError, match="timestamp"):
            export_srt(db.get(ProcessingJob, job_id))


def test_phase5_frontend_integration_and_accessibility(client: TestClient) -> None:
    html = client.get("/").text
    javascript = client.get("/static/js/app.js").text
    css = client.get("/static/css/app.css").text
    for value in [
        "transcriptSearch", "copyButton", 'data-format="txt"', 'data-format="json"',
        'data-format="srt"', 'aria-live="polite"', 'role="alert"', 'role="tab"',
    ]:
        assert value in html
    assert "Identity" in html and "Unknown" in html
    assert "toLocaleLowerCase" in javascript
    assert "document.createTextNode" in javascript
    assert 'document.createElement("mark")' in javascript
    assert "paragraph.replaceChildren" in javascript and "innerHTML" not in javascript
    assert "navigator.clipboard" in javascript and "document.execCommand" in javascript
    assert "Transcript copied" in javascript and "Detected language:" in javascript
    assert "preview.currentTime = Math.min" in javascript
    assert "loadedmetadata" in javascript and "timeupdate" in javascript
    assert "URL.revokeObjectURL" in javascript and "requestGeneration" in javascript
    assert "generation !== requestGeneration" in javascript and "if (isActive()" in javascript
    assert 'state = "failed"' in javascript and "clearWorkflow" in javascript
    assert "prefers-reduced-motion" in css and "max-width:420px" in css


def test_openapi_phase5_and_export_paths(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()
    assert schema["info"]["version"] == "0.5.0"
    assert "/api/jobs/{job_id}/transcript.{extension}" in schema["paths"]

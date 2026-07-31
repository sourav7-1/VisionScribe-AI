import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.database import SessionLocal
from app.main import app
from app.models.processing_job import ProcessingJob
from app.services import job_service
from app.services.face_detection_service import FaceDetectionResult
from app.services.job_service import create_job
from app.services.video_service import probe_video
from app.utils.errors import AppError


@pytest.fixture
def client() -> TestClient:
    with TestClient(app) as test_client:
        yield test_client


async def discard_background(_: str, path: Path | None) -> None:
    if path:
        path.unlink(missing_ok=True)


def test_valid_uploaded_mp4_is_accepted(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.routes.jobs.process_job", discard_background)
    response = client.post(
        "/api/jobs/upload", files={"video": ("clip.mp4", b"media", "video/mp4")}
    )
    assert response.status_code == 202
    assert response.json()["poll_url"].startswith("/api/jobs/")


def test_valid_direct_public_url_is_accepted(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def allow_url(_: str) -> None:
        return None

    monkeypatch.setattr("app.routes.jobs.validate_public_url", allow_url)
    monkeypatch.setattr("app.routes.jobs.process_job", discard_background)
    response = client.post("/api/jobs/url", json={"url": "https://example.com/video.mp4"})
    assert response.status_code == 202


@pytest.mark.parametrize(
    "url", ["http://localhost/video.mp4", "http://127.0.0.1/video.mp4", "http://[::1]/v.mp4"]
)
def test_unsafe_local_urls_are_rejected(client: TestClient, url: str) -> None:
    response = client.post("/api/jobs/url", json={"url": url})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "unsafe_private_url"


def test_unsupported_extension(client: TestClient) -> None:
    response = client.post(
        "/api/jobs/upload", files={"video": ("clip.txt", b"media", "video/mp4")}
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "unsupported_video_format"


def test_unsupported_mime_type(client: TestClient) -> None:
    response = client.post(
        "/api/jobs/upload", files={"video": ("clip.mp4", b"media", "text/plain")}
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "unsupported_mime_type"


def test_empty_file(client: TestClient) -> None:
    response = client.post(
        "/api/jobs/upload", files={"video": ("clip.mp4", b"", "video/mp4")}
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "empty_file"


def test_file_size_limit(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "max_upload_size_mb", 0)
    response = client.post(
        "/api/jobs/upload", files={"video": ("clip.mp4", b"x", "video/mp4")}
    )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "file_too_large"


@pytest.mark.parametrize(
    ("code", "message"),
    [
        ("corrupted_video", "corrupted"),
        ("missing_audio_stream", "audio"),
        ("video_too_long", "duration"),
    ],
)
def test_background_validation_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, code: str, message: str
) -> None:
    path = tmp_path / "video.mp4"
    path.write_bytes(b"video")
    with SessionLocal() as db:
        job = create_job(db, "upload", "video.mp4")
        job_id = job.id

    async def fail_probe(_: Path, __: object) -> dict:
        raise AppError(code, message)

    monkeypatch.setattr(job_service, "probe_video", fail_probe)
    asyncio.run(job_service.process_job(job_id, path))
    with SessionLocal() as db:
        result = db.get(ProcessingJob, job_id)
        assert result is not None
        assert result.status == "failed"
        assert result.error_message == message
    assert not path.exists()


def test_unknown_job_has_structured_404(client: TestClient) -> None:
    response = client.get("/api/jobs/not-a-job")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "unknown_job"


def test_ffprobe_unavailable(tmp_path: Path) -> None:
    settings = get_settings().model_copy(update={"ffprobe_binary": str(tmp_path / "missing.exe")})
    with pytest.raises(AppError, match="FFprobe is unavailable"):
        asyncio.run(probe_video(tmp_path / "video.mp4", settings))


def test_background_completion_and_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "valid.mp4"
    path.write_bytes(b"video")
    with SessionLocal() as db:
        job_id = create_job(db, "upload", "valid.mp4").id

    async def successful_probe(_: Path, __: object) -> dict:
        return {
            "duration": 3.5,
            "video_codec": "h264",
            "audio_codec": "aac",
            "width": 640,
            "height": 360,
        }

    monkeypatch.setattr(job_service, "probe_video", successful_probe)
    monkeypatch.setattr(
        job_service,
        "detect_faces_in_video",
        lambda *_: FaceDetectionResult(False, 0, 1, None, None, "CPU"),
    )
    asyncio.run(job_service.process_job(job_id, path))
    with SessionLocal() as db:
        result = db.get(ProcessingJob, job_id)
        assert result is not None
        assert result.status == "completed"
        assert result.progress == 100
        assert result.video_duration == 3.5
        assert "Phase 4" in result.current_stage
    assert not path.exists()


def test_openapi_version(client: TestClient) -> None:
    assert client.get("/openapi.json").json()["info"]["version"] == "0.3.0"

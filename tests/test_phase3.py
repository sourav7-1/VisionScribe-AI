import asyncio
import sys
import types
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text

from app.config import get_settings
from app.database import SessionLocal, migrate_sqlite_schema
from app.main import app
from app.models.processing_job import ProcessingJob
from app.services import face_detection_service as face_service
from app.services import job_service
from app.services.face_detection_service import (
    DetectorManager,
    FaceDetectionResult,
    calculate_face_results,
    detect_faces_in_video,
)
from app.services.job_service import create_job
from app.utils import device_detection
from app.utils.errors import AppError


class FakeCV:
    CAP_PROP_POS_MSEC = 0


class FakeCapture:
    def __init__(self, frame_count: int) -> None:
        self.frame_count = frame_count
        self.read_count = 0
        self.released = False

    def set(self, *_: object) -> bool:
        return True

    def read(self) -> tuple[bool, object | None]:
        if self.read_count >= self.frame_count:
            return False, None
        self.read_count += 1
        return True, object()

    def release(self) -> None:
        self.released = True


def settings(**updates: object):
    return get_settings().model_copy(update=updates)


@pytest.mark.parametrize(
    ("scores", "detected", "maximum", "average", "best"),
    [
        ([[0.91], [], []], True, 1, 0.91, 0.91),
        ([[0.91], [0.88, 0.84], []], True, 2, 0.8766666667, 0.91),
        ([[], [], []], False, 0, None, None),
    ],
)
def test_face_result_calculation(
    scores: list[list[float]],
    detected: bool,
    maximum: int,
    average: float | None,
    best: float | None,
) -> None:
    result = calculate_face_results(scores, "CPU")
    assert result.face_detected is detected
    assert result.maximum_face_count == maximum
    assert result.sampled_frame_count == len(scores)
    if average is None:
        assert result.average_detection_confidence is None
    else:
        assert result.average_detection_confidence == pytest.approx(average)
    assert result.best_detection_confidence == best


def configure_detection(
    monkeypatch: pytest.MonkeyPatch,
    frame_count: int,
    scores: list[list[float]],
    candidates: list[tuple[str, str]] | None = None,
) -> FakeCapture:
    capture = FakeCapture(frame_count)
    monkeypatch.setattr(face_service, "_open_capture", lambda _: (FakeCV, capture))
    monkeypatch.setattr(
        face_service,
        "provider_candidates",
        lambda _: candidates or [(device_detection.CPU_PROVIDER, "CPU")],
    )
    monkeypatch.setattr(face_service.detector_manager, "get_detector", lambda *_: object())
    outputs = iter(scores)
    monkeypatch.setattr(face_service.detector_manager, "infer", lambda *_: next(outputs))
    return capture


def test_configurable_interval_and_maximum_sample_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capture = configure_detection(monkeypatch, 3, [[], [], []])
    result = detect_faces_in_video(
        Path("video.mp4"),
        20,
        settings(frame_sample_interval_seconds=2.0, max_sampled_frames=3),
    )
    assert result.sampled_frame_count == 3
    assert capture.read_count == 3
    assert capture.released


def test_invalid_video_opencv_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        face_service,
        "_open_capture",
        lambda _: (_ for _ in ()).throw(
            AppError("opencv_video_open_failed", "The video could not be opened with OpenCV.")
        ),
    )
    with pytest.raises(AppError, match="OpenCV"):
        detect_faces_in_video(Path("bad.mp4"), 1, settings())


def test_no_decodable_frames(monkeypatch: pytest.MonkeyPatch) -> None:
    configure_detection(monkeypatch, 0, [])
    with pytest.raises(AppError, match="No video frames"):
        detect_faces_in_video(Path("bad.mp4"), 1, settings())


def test_cuda_provider_available(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        device_detection,
        "available_onnx_providers",
        lambda: [device_detection.CUDA_PROVIDER, device_detection.CPU_PROVIDER],
    )
    assert device_detection.provider_candidates("auto")[0] == (
        device_detection.CUDA_PROVIDER,
        "CUDA",
    )


def test_cuda_unavailable_uses_cpu(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        device_detection,
        "available_onnx_providers",
        lambda: [device_detection.CPU_PROVIDER],
    )
    assert device_detection.provider_candidates("auto") == [
        (device_detection.CPU_PROVIDER, "CPU")
    ]


def test_cuda_initialization_failure_falls_back_to_cpu(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capture = FakeCapture(1)
    monkeypatch.setattr(face_service, "_open_capture", lambda _: (FakeCV, capture))
    monkeypatch.setattr(
        face_service,
        "provider_candidates",
        lambda _: [
            (device_detection.CUDA_PROVIDER, "CUDA"),
            (device_detection.CPU_PROVIDER, "CPU"),
        ],
    )

    def initialize(provider: str, _: object) -> object:
        if provider == device_detection.CUDA_PROVIDER:
            raise AppError("face_detector_load_failed", "load failed")
        return object()

    monkeypatch.setattr(face_service.detector_manager, "get_detector", initialize)
    monkeypatch.setattr(face_service.detector_manager, "infer", lambda *_: [0.9])
    result = detect_faces_in_video(Path("video.mp4"), 1, settings())
    assert result.inference_device == "CPU"


def test_cuda_inference_failure_falls_back_to_cpu(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capture = FakeCapture(1)
    monkeypatch.setattr(face_service, "_open_capture", lambda _: (FakeCV, capture))
    monkeypatch.setattr(
        face_service,
        "provider_candidates",
        lambda _: [
            (device_detection.CUDA_PROVIDER, "CUDA"),
            (device_detection.CPU_PROVIDER, "CPU"),
        ],
    )
    cuda_detector, cpu_detector = object(), object()
    monkeypatch.setattr(
        face_service.detector_manager,
        "get_detector",
        lambda provider, _: cuda_detector
        if provider == device_detection.CUDA_PROVIDER
        else cpu_detector,
    )

    def infer(detector: object, _: object) -> list[float]:
        if detector is cuda_detector:
            raise RuntimeError("CUDA DLL failure")
        return [0.92]

    monkeypatch.setattr(face_service.detector_manager, "infer", infer)
    result = detect_faces_in_video(Path("video.mp4"), 1, settings())
    assert result.inference_device == "CPU"
    assert result.face_detected


def test_both_gpu_and_cpu_inference_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    configure_detection(
        monkeypatch,
        1,
        [[]],
        [
            (device_detection.CUDA_PROVIDER, "CUDA"),
            (device_detection.CPU_PROVIDER, "CPU"),
        ],
    )
    monkeypatch.setattr(
        face_service.detector_manager,
        "infer",
        lambda *_: (_ for _ in ()).throw(RuntimeError("failure")),
    )
    with pytest.raises(AppError, match="CPU fallback"):
        detect_faces_in_video(Path("video.mp4"), 1, settings())


def test_model_initializes_only_once(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls = 0

    class FakeAnalysis:
        def __init__(self, **_: object) -> None:
            nonlocal calls
            calls += 1
            self.taskname = "detection"
            self.session = types.SimpleNamespace(
                get_providers=lambda: [device_detection.CPU_PROVIDER]
            )

        def prepare(self, *_: object, **__: object) -> None:
            return None

    package = types.ModuleType("insightface")
    model_zoo_module = types.ModuleType("insightface.model_zoo")
    model_zoo_module.model_zoo = types.SimpleNamespace(
        get_model=lambda *_args, **_kwargs: FakeAnalysis()
    )
    utils_module = types.ModuleType("insightface.utils")
    model_dir = tmp_path / "models" / "buffalo_l"
    model_dir.mkdir(parents=True)
    (model_dir / "det_10g.onnx").touch()
    utils_module.ensure_available = lambda *_args, **_kwargs: str(model_dir)
    monkeypatch.setitem(sys.modules, "insightface", package)
    monkeypatch.setitem(sys.modules, "insightface.model_zoo", model_zoo_module)
    monkeypatch.setitem(sys.modules, "insightface.utils", utils_module)
    manager = DetectorManager()
    config = settings(face_model_root=tmp_path)
    first = manager.get_detector(device_detection.CPU_PROVIDER, config)
    second = manager.get_detector(device_detection.CPU_PROVIDER, config)
    assert first is second
    assert calls == 1


@pytest.mark.parametrize("should_fail", [False, True])
def test_job_cleanup_after_face_detection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, should_fail: bool
) -> None:
    path = tmp_path / "video.mp4"
    path.write_bytes(b"video")
    with SessionLocal() as db:
        job_id = create_job(db, "upload", "video.mp4").id

    async def metadata_probe(_: Path, __: object) -> dict:
        return {"duration": 2.0}

    def detection(*_: object) -> FaceDetectionResult:
        if should_fail:
            raise AppError("face_detection_failed", "Face detection could not be completed.")
        return FaceDetectionResult(True, 1, 2, 0.9, 0.9, "CPU")

    monkeypatch.setattr(job_service, "probe_video", metadata_probe)
    monkeypatch.setattr(job_service, "detect_faces_in_video", detection)
    asyncio.run(job_service.process_job(job_id, path))
    assert not path.exists()
    with SessionLocal() as db:
        job = db.get(ProcessingJob, job_id)
        assert job is not None
        assert job.status == ("failed" if should_fail else "completed")


def test_polling_contains_phase3_results() -> None:
    with SessionLocal() as db:
        job = create_job(db, "upload", "video.mp4")
        job.face_detected = True
        job.maximum_face_count = 2
        job.sampled_frame_count = 3
        job.average_detection_confidence = 0.87
        job.best_detection_confidence = 0.91
        job.inference_device = "CPU"
        db.commit()
        job_id = job.id
    with TestClient(app) as client:
        payload = client.get(f"/api/jobs/{job_id}").json()
    assert payload["face_detected"] is True
    assert payload["id"] == job_id
    assert payload["inference_device"] == "CPU"
    assert "transcript_json" in payload


def test_frontend_identity_and_disabled_transcript() -> None:
    with TestClient(app) as client:
        html = client.get("/").text
    assert "Identity" in html and "Unknown" in html
    assert "detection confidence" in html.lower()
    assert 'aria-label="Search transcript"' in html
    assert "disabled" in html


def test_existing_phase2_database_migration(tmp_path: Path) -> None:
    database = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with database.begin() as connection:
        connection.execute(text("CREATE TABLE processing_jobs (id VARCHAR(36) PRIMARY KEY)"))
    migrate_sqlite_schema(database)
    columns = {column["name"] for column in inspect(database).get_columns("processing_jobs")}
    assert "inference_device" in columns

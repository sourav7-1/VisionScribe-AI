import asyncio
import sys
import types
import wave
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.database import SessionLocal
from app.main import app
from app.models.processing_job import ProcessingJob
from app.services import job_service
from app.services.audio_service import extract_audio
from app.services.face_detection_service import FaceDetectionResult
from app.services.job_service import create_job
from app.services.transcription_service import (
    TranscriptionResult,
    WhisperModelManager,
    _candidates,
    transcribe_audio,
    whisper_manager,
)
from app.utils.errors import AppError
from app.utils.timestamp import format_timestamp


class Segment:
    def __init__(self, start: float, end: float, text: str) -> None:
        self.start, self.end, self.text = start, end, text


def config(**updates: object):
    return get_settings().model_copy(update=updates)


def make_wav(path: Path, rate: int = 8000, channels: int = 2) -> None:
    with wave.open(str(path), "wb") as output:
        output.setnchannels(channels)
        output.setsampwidth(2)
        output.setframerate(rate)
        output.writeframes(b"\0\0" * (channels * rate // 10))


def test_ffmpeg_extracts_unique_mono_16khz_wav(tmp_path: Path) -> None:
    source = tmp_path / "source.wav"
    make_wav(source)
    settings = config(temp_dir=tmp_path)
    first = asyncio.run(extract_audio(source, settings))
    second = asyncio.run(extract_audio(source, settings))
    try:
        assert first != second
        with wave.open(str(first), "rb") as audio:
            assert audio.getnchannels() == 1
            assert audio.getframerate() == 16000
    finally:
        first.unlink(missing_ok=True)
        second.unlink(missing_ok=True)


@pytest.mark.parametrize(
    ("language", "texts"),
    [
        ("bn", ["সবাইকে স্বাগতম।", "আজকে আমার project সম্পর্কে বলব।"]),
        ("en", ["Welcome everyone.", "This is my project."]),
        ("bn", ["আজকে my project নিয়ে কথা বলব।"]),
    ],
)
def test_transcript_languages_unicode_timestamps_and_speaker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    language: str,
    texts: list[str],
) -> None:
    raw = [Segment(index + 0.12, index + 0.75, text) for index, text in enumerate(texts)]
    info = types.SimpleNamespace(language=language, language_probability=0.94, duration=4.0)
    monkeypatch.setattr(
        whisper_manager, "get_model", lambda *_: object()
    )
    monkeypatch.setattr(whisper_manager, "run", lambda *_: (iter(raw), info))
    monkeypatch.setattr(
        "app.services.transcription_service._candidates", lambda _: [("cpu", "int8", "CPU")]
    )
    result = transcribe_audio(tmp_path / "audio.wav", config())
    assert result.language == language
    assert result.language_probability == 0.94
    assert [item["text"] for item in result.segments] == texts
    assert all(item["speaker"] == "Person 1" for item in result.segments)
    assert result.segments[0]["start"] == pytest.approx(0.12)
    assert result.segments == sorted(result.segments, key=lambda item: item["id"])


def test_empty_segments_and_silence_return_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    info = types.SimpleNamespace(language="en", language_probability=0.4, duration=1.0)
    monkeypatch.setattr(whisper_manager, "get_model", lambda *_: object())
    monkeypatch.setattr(
        whisper_manager, "run", lambda *_: (iter([Segment(0, 1, "   ")]), info)
    )
    monkeypatch.setattr(
        "app.services.transcription_service._candidates", lambda _: [("cpu", "int8", "CPU")]
    )
    assert transcribe_audio(tmp_path / "silent.wav", config()).segments == []


@pytest.mark.parametrize("language", [None, "bn", "en"])
def test_language_auto_and_forced_passed_to_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, language: str | None
) -> None:
    seen: dict[str, object] = {}

    class Model:
        def transcribe(self, _: str, **kwargs: object):
            seen.update(kwargs)
            return iter([]), types.SimpleNamespace(language=language, language_probability=1.0)

    manager = WhisperModelManager()
    manager.run(Model(), tmp_path / "a.wav", config(whisper_language=language))
    assert seen["language"] == language


def test_cuda_candidates_and_cpu_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = types.SimpleNamespace(get_supported_compute_types=lambda _: {"float16", "float32"})
    monkeypatch.setitem(sys.modules, "ctranslate2", fake)
    assert _candidates(config())[0] == ("cuda", "float16", "CUDA")
    fake.get_supported_compute_types = lambda _: (_ for _ in ()).throw(RuntimeError())
    assert _candidates(config()) == [("cpu", "int8", "CPU")]


def test_cuda_inference_failure_retries_cpu(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cuda, cpu = object(), object()
    monkeypatch.setattr(
        "app.services.transcription_service._candidates",
        lambda _: [("cuda", "float16", "CUDA"), ("cpu", "int8", "CPU")],
    )
    monkeypatch.setattr(
        whisper_manager, "get_model", lambda device, *_: cuda if device == "cuda" else cpu
    )

    def run(model: object, *_: object):
        if model is cuda:
            raise RuntimeError("CUDA failure")
        return iter([Segment(0, 1, "ok")]), types.SimpleNamespace(language="en")

    monkeypatch.setattr(whisper_manager, "run", run)
    assert transcribe_audio(tmp_path / "a.wav", config()).device == "CPU"


def test_cpu_failure_is_safe_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.services.transcription_service._candidates", lambda _: [("cpu", "int8", "CPU")]
    )
    monkeypatch.setattr(whisper_manager, "get_model", lambda *_: object())
    monkeypatch.setattr(
        whisper_manager, "run", lambda *_: (_ for _ in ()).throw(RuntimeError("failure"))
    )
    with pytest.raises(AppError, match="could not be completed"):
        transcribe_audio(tmp_path / "a.wav", config())


def test_model_initialized_once_and_reused(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls = 0

    class FakeModel:
        def __init__(self, *_: object, **__: object) -> None:
            nonlocal calls
            calls += 1

    module = types.ModuleType("faster_whisper")
    module.WhisperModel = FakeModel
    monkeypatch.setitem(sys.modules, "faster_whisper", module)
    manager = WhisperModelManager()
    settings = config(whisper_download_root=tmp_path)
    assert manager.get_model("cpu", "int8", settings) is manager.get_model(
        "cpu", "int8", settings
    )
    assert calls == 1


@pytest.mark.parametrize(
    ("face", "enabled", "expected"),
    [
        (False, False, "skipped"),
        (False, True, "completed"),
        (True, False, "completed"),
    ],
)
def test_face_dependent_transcription_and_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    face: bool,
    enabled: bool,
    expected: str,
) -> None:
    video = tmp_path / "video.mp4"
    audio = tmp_path / "audio.wav"
    video.write_bytes(b"video")
    with SessionLocal() as db:
        job_id = create_job(db, "upload", "video.mp4").id

    async def probe(*_: object) -> dict:
        return {"duration": 2.0, "has_audio": True}

    async def extraction(*_: object) -> Path:
        audio.write_bytes(b"audio")
        return audio

    monkeypatch.setattr(job_service, "probe_video", probe)
    monkeypatch.setattr(
        job_service,
        "detect_faces_in_video",
        lambda *_: FaceDetectionResult(
            face,
            int(face),
            2,
            0.9 if face else None,
            0.9 if face else None,
            "CPU",
        ),
    )
    monkeypatch.setattr(job_service, "extract_audio", extraction)
    monkeypatch.setattr(
        job_service,
        "transcribe_audio",
        lambda *_: TranscriptionResult([], "en", 0.9, "CPU", 2.0),
    )
    monkeypatch.setattr(get_settings(), "transcribe_without_face", enabled)
    asyncio.run(job_service.process_job(job_id, video))
    with SessionLocal() as db:
        job = db.get(ProcessingJob, job_id)
        assert job is not None and job.transcription_status == expected
    assert not video.exists()
    assert not audio.exists()


def test_missing_audio_preserves_face_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    video = tmp_path / "video.mp4"
    video.write_bytes(b"video")
    with SessionLocal() as db:
        job_id = create_job(db, "upload", "video.mp4").id

    async def probe(*_: object) -> dict:
        return {"duration": 2.0, "has_audio": False}

    monkeypatch.setattr(job_service, "probe_video", probe)
    monkeypatch.setattr(
        job_service,
        "detect_faces_in_video",
        lambda *_: FaceDetectionResult(True, 1, 2, 0.9, 0.9, "CPU"),
    )
    asyncio.run(job_service.process_job(job_id, video))
    with SessionLocal() as db:
        job = db.get(ProcessingJob, job_id)
        assert job is not None and job.face_detected is True
        assert job.transcription_status == "unavailable"


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [(3.2, "00:03"), (69.4, "01:09"), (3665, "01:01:05")],
)
def test_timestamp_formatting(seconds: float, expected: str) -> None:
    assert format_timestamp(seconds) == expected


def test_frontend_safe_chat_and_seek() -> None:
    with TestClient(app) as client:
        html = client.get("/").text
        javascript = client.get("/static/js/app.js").text
    assert "Identity" in html and "Unknown" in html
    assert "text.textContent = segment.text" in javascript
    assert "preview.currentTime = segment.start" in javascript
    assert "Person 1" in javascript
    assert "innerHTML" not in javascript

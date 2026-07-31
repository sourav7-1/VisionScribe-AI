import logging
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.config import Settings
from app.utils.errors import AppError

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TranscriptionResult:
    segments: list[dict]
    language: str | None
    language_probability: float | None
    device: str
    audio_duration: float | None


class WhisperModelManager:
    def __init__(self) -> None:
        self._models: dict[tuple[str, str, str, str], Any] = {}
        self._failed: set[tuple[str, str, str, str]] = set()
        self._init_lock = threading.Lock()
        self._inference_lock = threading.Lock()

    def reset(self) -> None:
        with self._init_lock:
            self._models.clear()
            self._failed.clear()

    def get_model(self, device: str, compute_type: str, settings: Settings) -> Any:
        key = (settings.whisper_model, device, compute_type, str(settings.whisper_download_root))
        if key in self._models:
            return self._models[key]
        if key in self._failed:
            raise AppError("whisper_model_unavailable", "The transcription model is unavailable.")
        with self._init_lock:
            if key in self._models:
                return self._models[key]
            try:
                from faster_whisper import WhisperModel

                settings.whisper_download_root.mkdir(parents=True, exist_ok=True)
                model = WhisperModel(
                    settings.whisper_model,
                    device=device,
                    compute_type=compute_type,
                    download_root=str(settings.whisper_download_root),
                )
            except Exception as exc:
                self._failed.add(key)
                raise AppError(
                    "whisper_model_unavailable", "The transcription model could not be loaded."
                ) from exc
            self._models[key] = model
            return model

    def run(self, model: Any, audio_path: Path, settings: Settings) -> tuple[Any, Any]:
        with self._inference_lock:
            return model.transcribe(
                str(audio_path),
                language=settings.whisper_language,
                beam_size=settings.whisper_beam_size,
                vad_filter=settings.whisper_vad_filter,
                condition_on_previous_text=settings.whisper_condition_on_previous_text,
            )


whisper_manager = WhisperModelManager()


def _candidates(settings: Settings) -> list[tuple[str, str, str]]:
    cpu_compute = (
        settings.whisper_compute_type
        if settings.whisper_compute_type != "auto"
        else settings.whisper_cpu_compute_type
    )
    cuda_compute = (
        settings.whisper_compute_type
        if settings.whisper_compute_type != "auto"
        else settings.whisper_cuda_compute_type
    )
    if settings.whisper_device == "cpu":
        return [("cpu", cpu_compute, "CPU")]
    candidates: list[tuple[str, str, str]] = []
    try:
        import ctranslate2

        if "float16" in ctranslate2.get_supported_compute_types("cuda"):
            candidates.append(("cuda", cuda_compute, "CUDA"))
    except Exception:
        logger.warning("CTranslate2 CUDA is unavailable; using CPU fallback")
    candidates.append(("cpu", cpu_compute, "CPU"))
    return candidates


def _clean_segments(raw_segments: Any) -> list[dict]:
    output: list[dict] = []
    for segment in raw_segments:
        text = str(segment.text).strip()
        if not text:
            continue
        output.append(
            {
                "id": len(output) + 1,
                "start": float(segment.start),
                "end": float(segment.end),
                "speaker": "Person 1",
                "text": text,
            }
        )
    return output


def transcribe_audio(audio_path: Path, settings: Settings) -> TranscriptionResult:
    last_error: Exception | None = None
    for device, compute_type, label in _candidates(settings):
        try:
            model = whisper_manager.get_model(device, compute_type, settings)
            raw_segments, info = whisper_manager.run(model, audio_path, settings)
            segments = _clean_segments(raw_segments)
            return TranscriptionResult(
                segments=segments,
                language=getattr(info, "language", None),
                language_probability=getattr(info, "language_probability", None),
                device=label,
                audio_duration=getattr(info, "duration", None),
            )
        except Exception as exc:
            last_error = exc
            if device == "cuda":
                logger.warning("CUDA transcription failed; retrying once on CPU")
                continue
            break
    raise AppError(
        "transcription_failed", "Speech transcription could not be completed."
    ) from last_error

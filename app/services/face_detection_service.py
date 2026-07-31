import logging
import math
import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from glob import glob
from pathlib import Path
from typing import Any

from app.config import Settings
from app.utils.device_detection import CPU_PROVIDER, provider_candidates
from app.utils.errors import AppError

logger = logging.getLogger(__name__)
ProgressCallback = Callable[[int, str], None]


@dataclass(frozen=True)
class FaceDetectionResult:
    face_detected: bool
    maximum_face_count: int
    sampled_frame_count: int
    average_detection_confidence: float | None
    best_detection_confidence: float | None
    inference_device: str


def calculate_face_results(
    frame_scores: Iterable[Iterable[float]], inference_device: str
) -> FaceDetectionResult:
    frames = [list(scores) for scores in frame_scores]
    valid_scores = [score for scores in frames for score in scores]
    return FaceDetectionResult(
        face_detected=bool(valid_scores),
        maximum_face_count=max((len(scores) for scores in frames), default=0),
        sampled_frame_count=len(frames),
        average_detection_confidence=(sum(valid_scores) / len(valid_scores))
        if valid_scores
        else None,
        best_detection_confidence=max(valid_scores) if valid_scores else None,
        inference_device=inference_device,
    )


class DetectorManager:
    def __init__(self) -> None:
        self._detectors: dict[tuple[Any, ...], Any] = {}
        self._failed_initializations: set[tuple[Any, ...]] = set()
        self._initialization_lock = threading.Lock()
        self._inference_lock = threading.Lock()

    def reset(self) -> None:
        with self._initialization_lock:
            self._detectors.clear()
            self._failed_initializations.clear()

    def get_detector(self, provider: str, settings: Settings) -> Any:
        key = (
            provider,
            settings.face_model_name,
            str(settings.face_model_root),
            settings.face_detection_size,
            settings.face_detection_threshold,
        )
        detector = self._detectors.get(key)
        if detector is not None:
            return detector
        if key in self._failed_initializations:
            raise AppError(
                "face_detector_load_failed",
                "The face detector model could not be loaded.",
                503,
            )
        with self._initialization_lock:
            detector = self._detectors.get(key)
            if detector is not None:
                return detector
            if key in self._failed_initializations:
                raise AppError(
                    "face_detector_load_failed",
                    "The face detector model could not be loaded.",
                    503,
                )
            try:
                from insightface.model_zoo import model_zoo
                from insightface.utils import ensure_available

                model_dir = ensure_available(
                    "models", settings.face_model_name, root=str(settings.face_model_root)
                )
                detection_files = sorted(
                    path
                    for path in glob(str(Path(model_dir) / "*.onnx"))
                    if Path(path).stem.lower().startswith(("det_", "scrfd"))
                )
                if not detection_files:
                    raise RuntimeError("No SCRFD detection ONNX model was found")
                detector = model_zoo.get_model(detection_files[0], providers=[provider])
                if detector is None or detector.taskname != "detection":
                    raise RuntimeError("The configured model is not an SCRFD detector")
                detector.prepare(
                    ctx_id=0 if provider != CPU_PROVIDER else -1,
                    input_size=(settings.face_detection_size, settings.face_detection_size),
                    det_thresh=settings.face_detection_threshold,
                )
                active_providers = detector.session.get_providers()
                if provider not in active_providers:
                    raise RuntimeError(
                        f"Requested provider {provider} is not active in the detector session"
                    )
            except Exception as exc:
                self._failed_initializations.add(key)
                raise AppError(
                    "face_detector_load_failed",
                    "The face detector model could not be loaded.",
                    503,
                ) from exc
            self._detectors[key] = detector
            return detector

    def infer(self, detector: Any, frame: Any) -> list[float]:
        with self._inference_lock:
            boxes, _ = detector.detect(frame)
        return [float(box[4]) for box in boxes if len(box) >= 5]


detector_manager = DetectorManager()


def _open_capture(path: Path) -> Any:
    try:
        import cv2
    except (ImportError, OSError) as exc:
        raise AppError(
            "opencv_unavailable", "OpenCV is unavailable. Install the Phase 3 AI dependencies.", 503
        ) from exc
    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        capture.release()
        raise AppError("opencv_video_open_failed", "The video could not be opened with OpenCV.")
    return cv2, capture


def _sample_timestamps(duration: float, interval: float, maximum: int) -> list[float]:
    if interval <= 0 or maximum <= 0:
        raise AppError("invalid_face_configuration", "Face sampling configuration is invalid.", 500)
    count = min(maximum, max(1, math.ceil(duration / interval)))
    return [index * interval for index in range(count)]


def detect_faces_in_video(
    path: Path,
    duration: float,
    settings: Settings,
    progress_callback: ProgressCallback | None = None,
) -> FaceDetectionResult:
    cv2, capture = _open_capture(path)
    timestamps = _sample_timestamps(
        duration, settings.frame_sample_interval_seconds, settings.max_sampled_frames
    )
    candidates = provider_candidates(settings.face_device)
    provider_index = 0
    provider, device = candidates[provider_index]
    if progress_callback:
        progress_callback(35, "Loading face detector")
    try:
        try:
            detector = detector_manager.get_detector(provider, settings)
        except AppError:
            if provider != CPU_PROVIDER and len(candidates) > 1:
                logger.warning("CUDA detector initialization failed; falling back to CPU")
                provider_index += 1
                provider, device = candidates[provider_index]
                detector = detector_manager.get_detector(provider, settings)
            else:
                raise
        frame_scores: list[list[float]] = []
        for index, timestamp in enumerate(timestamps):
            capture.set(cv2.CAP_PROP_POS_MSEC, timestamp * 1000)
            decoded, frame = capture.read()
            if not decoded or frame is None:
                if index == 0:
                    raise AppError("no_decodable_frames", "No video frames could be decoded.")
                break
            try:
                scores = detector_manager.infer(detector, frame)
            except Exception as exc:
                if provider != CPU_PROVIDER and len(candidates) > provider_index + 1:
                    logger.warning("CUDA inference failed; retrying with CPU")
                    provider_index += 1
                    provider, device = candidates[provider_index]
                    detector = detector_manager.get_detector(provider, settings)
                    try:
                        scores = detector_manager.infer(detector, frame)
                    except Exception as cpu_exc:
                        raise AppError(
                            "face_detection_failed",
                            "CUDA inference failed and CPU fallback also failed.",
                        ) from cpu_exc
                else:
                    raise AppError(
                        "face_detection_failed", "Face detection could not be completed."
                    ) from exc
            scores = [score for score in scores if score >= settings.face_detection_threshold]
            frame_scores.append(scores)
            del frame
            if progress_callback:
                progress = 40 + round(15 * (index + 1) / len(timestamps))
                progress_callback(progress, "Detecting human faces")
        if not frame_scores:
            raise AppError("no_decodable_frames", "No video frames could be decoded.")
        return calculate_face_results(frame_scores, device)
    finally:
        capture.release()

import logging
from functools import lru_cache

from app.utils.errors import AppError

logger = logging.getLogger(__name__)
CUDA_PROVIDER = "CUDAExecutionProvider"
CPU_PROVIDER = "CPUExecutionProvider"


@lru_cache
def available_onnx_providers() -> list[str]:
    try:
        import onnxruntime as ort

        if hasattr(ort, "preload_dlls"):
            try:
                ort.preload_dlls(directory="")
            except RuntimeError:
                logger.warning("CUDA/cuDNN DLL preload failed; CPU fallback remains available")
        return list(ort.get_available_providers())
    except (ImportError, OSError) as exc:
        raise AppError(
            "face_detector_unavailable",
            "ONNX Runtime is unavailable. Install the Phase 3 AI dependencies.",
            503,
        ) from exc


def provider_candidates(face_device: str) -> list[tuple[str, str]]:
    providers = available_onnx_providers()
    cpu_available = CPU_PROVIDER in providers
    cuda_available = CUDA_PROVIDER in providers
    if face_device == "cuda" and not cuda_available:
        logger.warning("CUDA was requested but its ONNX Runtime provider is unavailable")
    candidates: list[tuple[str, str]] = []
    if face_device != "cpu" and cuda_available:
        candidates.append((CUDA_PROVIDER, "CUDA"))
    if cpu_available:
        candidates.append((CPU_PROVIDER, "CPU"))
    if not candidates:
        raise AppError(
            "face_detector_unavailable",
            "No supported ONNX Runtime execution provider is available.",
            503,
        )
    return candidates

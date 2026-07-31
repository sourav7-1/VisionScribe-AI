import os
import shutil
from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def discover_ffprobe() -> str:
    project_binary = PROJECT_ROOT / "tools" / "ffmpeg" / "bin" / "ffprobe.exe"
    if project_binary.exists():
        return str(project_binary)
    path_binary = shutil.which("ffprobe")
    if path_binary:
        return path_binary
    local_app_data = os.getenv("LOCALAPPDATA")
    if local_app_data:
        winget_root = Path(local_app_data) / "Microsoft" / "WinGet" / "Packages"
        matches = sorted(winget_root.glob("Gyan.FFmpeg_*/*/bin/ffprobe.exe"), reverse=True)
        if matches:
            return str(matches[0])
    return "ffprobe"


class Settings(BaseSettings):
    app_name: str = "VisionScribe AI"
    app_env: str = "development"
    debug: bool = Field(
        default=False,
        validation_alias=AliasChoices("VISIONSCRIBE_DEBUG", "DEBUG"),
    )
    host: str = "127.0.0.1"
    port: int = 8000
    database_url: str = f"sqlite:///{(PROJECT_ROOT / 'visionscribe.db').as_posix()}"
    cors_origins: list[str] = ["http://localhost:8000", "http://127.0.0.1:8000"]
    max_upload_size_mb: int = 500
    max_video_duration_seconds: int = 3600
    request_timeout_seconds: int = 120
    url_download_timeout_seconds: int = 120
    max_url_redirects: int = 3
    upload_chunk_size_bytes: int = 1048576
    ffprobe_binary: str = Field(default_factory=discover_ffprobe)
    log_level: str = "INFO"
    temp_dir: Path = PROJECT_ROOT / "temp"
    frame_sample_interval_seconds: float = 1.0
    max_sampled_frames: int = 600
    face_detection_threshold: float = 0.5
    face_detection_size: int = 640
    face_model_name: str = "buffalo_l"
    face_model_root: Path = PROJECT_ROOT / "models"
    face_device: str = "auto"
    transcribe_without_face: bool = False
    whisper_model: str = "medium"
    whisper_device: str = "auto"
    whisper_compute_type: str = "auto"

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: object) -> object:
        if isinstance(value, str) and not value.lstrip().startswith("["):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("debug", mode="before")
    @classmethod
    def parse_debug(cls, value: object) -> object:
        if isinstance(value, str) and value.lower() in {
            "debug",
            "info",
            "warn",
            "warning",
            "error",
            "release",
            "production",
        }:
            return False
        return value

    @field_validator("temp_dir", "face_model_root", mode="after")
    @classmethod
    def make_temp_dir_absolute(cls, value: Path) -> Path:
        return value if value.is_absolute() else PROJECT_ROOT / value

    @field_validator("face_device")
    @classmethod
    def validate_face_device(cls, value: str) -> str:
        normalized = value.lower()
        if normalized not in {"auto", "cuda", "cpu"}:
            raise ValueError("FACE_DEVICE must be auto, cuda, or cpu")
        return normalized


@lru_cache
def get_settings() -> Settings:
    return Settings()

# VisionScribe AI

VisionScribe AI is a privacy-conscious FastAPI application for securely ingesting an
authorized video before future face-presence detection and timestamped transcription.
It never identifies a person. Identity always remains **Unknown**.

## Phase 2 status

Phase 2 is complete:

- Chunked local upload and drag-and-drop
- Direct public HTTP/HTTPS video URL ingestion
- Extension, MIME type, size, stream, duration, and corruption validation
- SSRF defenses for DNS results and every redirect target
- Streaming remote downloads with timeouts, redirect limits, and size limits
- FFprobe metadata inspection
- SQLite processing-job creation and background processing
- One-second frontend progress polling, local preview, status, duration, and safe errors
- Temporary-file cleanup after success and failure
- Structured API errors and configurable internal logging

Face detection, identity recognition, CUDA inference, speech transcription, and AI model
downloads are deliberately not part of Phase 2.

## Architecture and workflow

```text
Browser dashboard
  -> POST /api/jobs/upload or /api/jobs/url
  -> FastAPI validation and SQLAlchemy job creation
  -> HTTP 202 with job ID and polling URL
  -> background streamed acquisition
  -> FFprobe stream and duration validation
  -> job completion/failure update
  -> temporary-file deletion
  -> GET /api/jobs/{job_id} polling
```

A successful job ends with:

```text
Ingestion complete — ready for face detection in Phase 3
```

## Phase 2 files

New:

- `app/routes/jobs.py`
- `app/schemas/job.py`
- `app/services/job_service.py`
- `app/services/video_service.py`
- `app/utils/errors.py`
- `app/utils/url_safety.py`
- `tests/test_phase2.py`

Updated:

- `app/main.py`
- `app/config.py`
- `app/models/processing_job.py`
- `templates/index.html`
- `static/css/app.css`
- `static/js/app.js`
- `.env.example`

## Windows setup (all project files on D:)

PowerShell:

```powershell
cd D:\VisionScribe-AI-Phase-1
.\.venv\Scripts\Activate.ps1
$env:DEBUG = "false"
python -m pip install -r requirements-dev.txt
python -m uvicorn app.main:app --reload
```

Command Prompt:

```cmd
cd /d D:\VisionScribe-AI-Phase-1
.venv\Scripts\activate.bat
set DEBUG=false
python -m pip install -r requirements-dev.txt
python -m uvicorn app.main:app --reload
```

Open <http://127.0.0.1:8000>. API documentation is at
<http://127.0.0.1:8000/docs>.

## FFmpeg and FFprobe

Check availability:

```cmd
ffmpeg -version
ffprobe -version
```

The default Phase 2 configuration supports project-local FFprobe at:

```text
D:\VisionScribe-AI-Phase-1\tools\ffmpeg\bin\ffprobe.exe
```

Alternatively, install system-wide with:

```cmd
winget install --id Gyan.FFmpeg
```

Never hardcode a personal machine path. Configure `FFPROBE_BINARY` when the executable is
elsewhere.

## Environment configuration

Copy `.env.example` to `.env` only if `.env` does not already exist. Never overwrite a
personalized `.env`.

New Phase 2 settings:

```env
LOG_LEVEL=INFO
URL_DOWNLOAD_TIMEOUT_SECONDS=120
MAX_URL_REDIRECTS=3
UPLOAD_CHUNK_SIZE_BYTES=1048576
FFPROBE_BINARY=tools/ffmpeg/bin/ffprobe.exe
```

Existing limits remain configurable through `MAX_UPLOAD_SIZE_MB`,
`MAX_VIDEO_DURATION_SECONDS`, `REQUEST_TIMEOUT_SECONDS`, `TEMP_DIR`, and `CORS_ORIGINS`.

## API examples

PowerShell upload:

```powershell
curl.exe -F "video=@D:\videos\authorized.mp4" http://127.0.0.1:8000/api/jobs/upload
```

Public URL:

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/jobs/url `
  -ContentType application/json `
  -Body '{"url":"https://example.com/video.mp4"}'
```

Poll a job:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/jobs/JOB_ID
```

## Tests and verification

```powershell
pytest -q
ruff check app tests
python -m compileall app
node --check static/js/app.js
```

Tests mock public downloads and do not depend on an external website. Media is never added
to the repository as a large permanent fixture.

## Security and privacy

- Process only content you own or are authorized to use.
- Only direct public HTTP/HTTPS video URLs are supported.
- Localhost, private, link-local, loopback, reserved, and credential-bearing URLs are
  rejected; redirect targets are checked again.
- Login-required, private, authenticated, and DRM-protected media is not bypassed.
- Downloads and uploads are streamed with configured time and size limits.
- Video bytes are never stored in the database.
- Temporary media is deleted after successful and failed processing.
- Sensitive URLs, credentials, and video bytes are not logged.
- Future UI terminology will be “Human face detected” or “No human face detected.”
- Face presence never proves identity, liveness, or authenticity.

## Phase 3 preview

Phase 3 will add sampled-frame human-face presence detection while keeping
`Identity: Unknown`. It will not be started without confirmation.

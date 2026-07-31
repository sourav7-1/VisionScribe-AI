# VisionScribe AI

VisionScribe AI 0.5.0 is a privacy-conscious local FastAPI dashboard for authorized
video analysis. It detects human-face presence with SCRFD and transcribes Bengali,
English, or mixed speech with Faster-Whisper. Identity always remains **Unknown**.

Phase 5 completes the integrated user experience. It does not add recognition,
diarization, face/voice matching, an LLM, or another AI model.

## Complete workflow

```text
upload or safe direct public URL
  -> validated temporary video and metadata
  -> sampled detection-only face analysis
  -> optional mono 16 kHz audio extraction
  -> timestamped local transcription
  -> face and transcript results saved to SQLite
  -> temporary audio/video deleted
  -> local search, copy, TXT/JSON/SRT download, seeking, and clear
```

The frontend prevents duplicate submissions, ignores stale polling responses, keeps
progress monotonic, stops polling on terminal states, and permits safe retry after a
server or network failure. A transcription warning preserves valid face results.

## Phase 5 transcript tools

- Search is local, debounced, case-insensitive for English, Unicode-safe for Bengali,
  and highlights matches using DOM text nodes and `<mark>`—never unsafe HTML.
- Copy includes detected language, `Identity: Unknown`, and the complete unfiltered
  transcript. It uses the Clipboard API with a browser fallback.
- Timestamp buttons wait for video metadata, clamp the seek to the playable duration,
  handle autoplay rejection, and track the active segment with `timeupdate`.
- Clear stops the current polling generation, revokes object URLs, resets every result
  and control, and does not delete historical database jobs.

Uploaded videos use a browser object URL for preview; old and final URLs are revoked.
Direct public URLs are previewed only when the browser supports them. CORS, login, and
DRM restrictions are never bypassed. If preview fails, timestamps remain readable but
seeking is unavailable.

## Transcript downloads

```http
GET /api/jobs/{job_id}/transcript.txt
GET /api/jobs/{job_id}/transcript.json
GET /api/jobs/{job_id}/transcript.srt
```

Exports are generated in memory as UTF-8 and never create persistent files. Filenames
are sanitized and include a short job ID. Unknown jobs return structured `404` errors;
incomplete, failed, or empty transcripts return structured `409` errors.

- TXT is human-readable and includes product title, `Identity: Unknown`, language,
  duration, and one timestamped `Person 1` segment per line.
- JSON contains only public result metadata and raw numeric segment timestamps. It does
  not expose source URLs, media paths, or model paths.
- SRT uses sequential blocks and validated `HH:MM:SS,mmm` ranges. It omits speaker
  identity and supports videos longer than one hour.

Example JSON:

```json
{
  "job_id": "job-id",
  "identity": "Unknown",
  "face_detected": true,
  "detected_language": "bn",
  "transcription_status": "completed",
  "segments": [
    {"id": 1, "start": 3.12, "end": 8.75, "speaker": "Person 1", "text": "সবাইকে স্বাগতম।"}
  ]
}
```

## Accessibility and responsive behavior

The dashboard includes real labels, keyboard tabs and timestamp buttons, visible focus
styles, progress/action live regions, alert semantics, accessible disabled states, and
an announced search result count. Reduced-motion preferences are respected. Result
cards, search controls, action buttons, filenames, and Bengali text wrap on laptop,
tablet, and mobile layouts without horizontal overflow.

## Install entirely on D: (PowerShell)

```powershell
cd D:\VisionScribe-AI-Phase-1
python -m venv .venv
.\.venv\Scripts\Activate.ps1
New-Item -ItemType Directory -Force .cache\pip,temp\pip,models\whisper | Out-Null
$env:PIP_CACHE_DIR = "D:\VisionScribe-AI-Phase-1\.cache\pip"
$env:TEMP = "D:\VisionScribe-AI-Phase-1\temp\pip"
$env:TMP = $env:TEMP
python -m pip install -r requirements-dev.txt
python -m pip install -r requirements-ai.txt
python -m pip install --no-deps -r requirements-whisper.txt
python -m pip install --no-deps -r requirements-insightface.txt
```

The `--no-deps` steps prevent CPU `onnxruntime` from being installed alongside the
project's `onnxruntime-gpu`, which already supplies CPU fallback. FFmpeg is discovered
from the project, PATH, or winget installation. All configured cache/model/temp paths
remain inside the project on `D:`.

## Run

```powershell
cd D:\VisionScribe-AI-Phase-1
.\.venv\Scripts\Activate.ps1
$env:VISIONSCRIBE_DEBUG = "false"
python -m uvicorn app.main:app --reload
```

Open <http://127.0.0.1:8000>.

## Verify

```powershell
$env:TEMP = "D:\VisionScribe-AI-Phase-1\temp"
$env:TMP = $env:TEMP
pytest -q --basetemp D:\VisionScribe-AI-Phase-1\temp\pytest
ruff check app tests
python -m compileall app
node --check static/js/app.js
```

Useful API checks:

```powershell
Invoke-WebRequest http://127.0.0.1:8000/api/health
Invoke-WebRequest http://127.0.0.1:8000/
Invoke-RestMethod http://127.0.0.1:8000/openapi.json
```

## Error, warning, privacy, and limitations

Fatal ingestion/detection errors are displayed separately from warnings. No-audio,
no-speech, skipped transcription, browser-preview failure, clipboard denial, and
transcription failure are warnings and never masquerade as successful transcription.
Stack traces, credentials, internal paths, and source URLs are not exposed in exports.

- Process only media you own or are authorized to use.
- Sampled frames, face crops, face/voice embeddings, biometric templates, uploaded
  videos, and extracted WAV files are not stored permanently.
- Transcript text and numerical job results remain in SQLite.
- `Person 1` is a neutral single-speaker label, not identification or diarization.
- Face detection does not prove identity, liveness, or authenticity.
- Transcription does not prove that a detected face produced the speech.
- Model output can be wrong, especially with noise, accents, and mixed languages.
- FastAPI background tasks are suitable for this local version, not durable multi-worker
  production processing.

InsightFace's supplied pretrained model packs have non-commercial research licensing
restrictions; confirm licensing before commercial use.

## Phase 6 preview

Phase 6 will cover final hardening, deployment review, release validation, and
production-readiness decisions. Phase 5 is complete but the project is not marked
production-ready.

# VisionScribe AI

VisionScribe AI 0.4.0 is a privacy-conscious local FastAPI application for authorized
video analysis. It performs detection-only face analysis and timestamped speech-to-text.
Face detection is not recognition: identity always remains **Unknown**.

## Phase 4 workflow

```text
upload or public URL
  -> validated temporary video
  -> sampled SCRFD face detection
  -> FFmpeg mono 16 kHz WAV extraction
  -> Faster-Whisper transcription (CUDA, then safe CPU fallback)
  -> language, timestamps, and "Person 1" segments saved to SQLite
  -> temporary audio and video deleted
```

Transcription normally runs only when a face was detected. Set
`TRANSCRIBE_WITHOUT_FACE=true` to override this. There is no diarization, speaker
identification, recognition, embedding generation, or face/voice association. A
transcription or audio failure is reported as a warning and preserves successful face
results.

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

FFmpeg is already supported through PATH/winget discovery. If needed:

```powershell
winget install --id Gyan.FFmpeg
```

Faster-Whisper model files download once to
`D:\VisionScribe-AI-Phase-1\models\whisper`. The default `medium` model is sizeable;
set `WHISPER_MODEL=tiny` for a small smoke test before starting the app. InsightFace's
detection model remains under the project `models` directory.

The `--no-deps` steps are intentional. Both InsightFace and Faster-Whisper declare
runtime variants that would otherwise install CPU `onnxruntime` beside
`onnxruntime-gpu`. `requirements-ai.txt` explicitly supplies their compatible runtime
dependencies while retaining one ONNX Runtime package with CUDA and CPU providers.

## Configuration

Copy `.env.example` to `.env`. Important Phase 4 settings are:

```env
FFMPEG_BINARY=ffmpeg
WHISPER_MODEL=medium
WHISPER_DEVICE=auto
WHISPER_COMPUTE_TYPE=auto
WHISPER_CPU_COMPUTE_TYPE=int8
WHISPER_CUDA_COMPUTE_TYPE=float16
WHISPER_DOWNLOAD_ROOT=models/whisper
WHISPER_LANGUAGE=
TRANSCRIBE_WITHOUT_FACE=false
AUDIO_SAMPLE_RATE=16000
AUDIO_CHANNELS=1
```

An empty `WHISPER_LANGUAGE` enables automatic language detection. Use `bn` or `en` to
force Bengali or English. CUDA is attempted only when CTranslate2 reports compatible
support; initialization or inference failure retries once on CPU with int8.

## Run

```powershell
cd D:\VisionScribe-AI-Phase-1
.\.venv\Scripts\Activate.ps1
$env:VISIONSCRIBE_DEBUG = "false"
python -m uvicorn app.main:app --reload
```

Open <http://127.0.0.1:8000>. Transcript timestamp buttons seek the local video preview.
Transcript text is inserted with DOM `textContent`, so transcribed markup is never
interpreted as HTML.

## API result

`GET /api/jobs/{job_id}` retains all Phase 2/3 fields and adds:

```json
{
  "status": "completed",
  "face_detected": true,
  "inference_device": "CPU",
  "transcription_status": "completed",
  "transcription_device": "CPU",
  "detected_language": "bn",
  "language_probability": 0.97,
  "audio_duration": 12.4,
  "transcription_segment_count": 2,
  "transcript_json": [
    {"id": 0, "start": 0.0, "end": 3.2, "text": "স্বাগতম।", "speaker": "Person 1"}
  ],
  "transcription_warning": null
}
```

Startup performs additive, idempotent SQLite migration for the new columns. Existing
records and all earlier fields are preserved; do not delete the database.

## Verify

```powershell
$env:TEMP = "D:\VisionScribe-AI-Phase-1\temp"
$env:TMP = $env:TEMP
pytest -q --basetemp D:\VisionScribe-AI-Phase-1\temp\pytest
ruff check app tests
python -m compileall app
node --check static/js/app.js
python -c "import ctranslate2; print(ctranslate2.get_supported_compute_types('cpu'))"
python -c "import ctranslate2; print(ctranslate2.get_supported_compute_types('cuda'))"
```

CTranslate2's CUDA check is the relevant Whisper capability check. A visible NVIDIA GPU
or a CUDA provider in ONNX Runtime does not guarantee that the required CUDA/cuDNN DLLs
for CTranslate2 are installed. CPU fallback is an expected supported mode.

## Privacy and limitations

- Process only videos you own or are authorized to use.
- Face frames, crops, coordinates, embeddings, biometric templates, and voiceprints are
  not stored.
- Audio and video working files are deleted after the whole job, including warning and
  failure paths.
- Transcript text and numerical detection metadata remain in SQLite as job results.
- "Person 1" is a neutral label, not an identified or diarized person.
- Detection does not prove identity, liveness, authenticity, or authorization.

InsightFace code is MIT licensed, while its supplied pretrained model packs have
non-commercial research restrictions. Confirm model licensing before commercial use.

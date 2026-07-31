# VisionScribe AI

VisionScribe AI is a privacy-conscious FastAPI application that securely ingests an
authorized video and uses SCRFD to detect whether at least one human face appears.
Detection is not recognition: **Identity always remains Unknown**.

## Phase 3 status

Phase 3 is complete:

- Phase 2 upload, public-URL validation, FFprobe, polling, and cleanup are preserved.
- OpenCV samples frames by timestamp instead of decoding every frame.
- Only the SCRFD detection ONNX model is loaded; recognition models and embeddings are
  never loaded, executed, generated, or stored.
- The detector model is initialized lazily once per active provider and reused safely.
- ONNX Runtime tries CUDA only when advertised, verifies the provider active in the real
  model session, and falls back to CPU after initialization or inference failures.
- Results include face presence, maximum visible faces, sampled frames, average and best
  detection confidence, and the actual inference device.
- Uploaded/downloaded video is deleted only after detection completes or fails.
- The dashboard shows real polling results and keeps all transcript controls disabled.

Successful jobs end with:

```text
Face detection complete — ready for transcription in Phase 4
```

Face detection only confirms that the detector found a face-like region. It does not
prove identity, liveness, or authenticity.

## Architecture and workflow

```text
Upload or direct public URL
  -> secure Phase 2 acquisition and FFprobe validation
  -> OpenCV timestamp sampling (bounded by MAX_SAMPLED_FRAMES)
  -> detection-only SCRFD ONNX session
  -> verified CUDA provider or automatic CPU fallback
  -> numerical results saved to SQLite
  -> temporary video deleted
  -> browser receives results through GET /api/jobs/{id}
```

FastAPI `BackgroundTasks` is suitable for local Version 1. A durable external job queue is
required before multi-worker production deployment.

## Files

Created in Phase 3:

- `app/services/face_detection_service.py`
- `app/utils/device_detection.py`
- `tests/test_phase3.py`
- `requirements-ai.txt`
- `requirements-insightface.txt`

Modified:

- `app/config.py`
- `app/database.py`
- `app/main.py`
- `app/models/processing_job.py`
- `app/routes/jobs.py`
- `app/schemas/job.py`
- `app/services/job_service.py`
- `.env.example`
- `.gitignore`
- `static/css/app.css`
- `static/js/app.js`
- `templates/index.html`
- `tests/test_phase2.py`
- `README.md`

## Database migration

Startup safely inspects an existing SQLite `processing_jobs` table. If required, it runs:

```sql
ALTER TABLE processing_jobs ADD COLUMN inference_device VARCHAR(16)
```

Existing records and Phase 2 fields are preserved. Do not delete the database.

## Installation on D: (PowerShell)

```powershell
cd D:\VisionScribe-AI-Phase-1
.\.venv\Scripts\Activate.ps1
$env:VISIONSCRIBE_DEBUG = "false"
$env:PIP_CACHE_DIR = "D:\VisionScribe-AI-Phase-1\.cache\pip"
$env:TEMP = "D:\VisionScribe-AI-Phase-1\temp\pip"
$env:TMP = $env:TEMP
python -m pip install -r requirements-dev.txt
python -m pip install -r requirements-ai.txt
python -m pip install --no-deps -r requirements-insightface.txt
```

Command Prompt:

```cmd
cd /d D:\VisionScribe-AI-Phase-1
.venv\Scripts\activate.bat
set VISIONSCRIBE_DEBUG=false
set PIP_CACHE_DIR=D:\VisionScribe-AI-Phase-1\.cache\pip
set TEMP=D:\VisionScribe-AI-Phase-1\temp\pip
set TMP=D:\VisionScribe-AI-Phase-1\temp\pip
python -m pip install -r requirements-dev.txt
python -m pip install -r requirements-ai.txt
python -m pip install --no-deps -r requirements-insightface.txt
```

The two-step InsightFace installation is intentional. Its metadata requests CPU
`onnxruntime` and GUI `opencv-python`; this project instead keeps only
`onnxruntime-gpu` (which includes CPU fallback) and `opencv-python-headless`.

If InsightFace cannot install on another Windows machine, update pip first. InsightFace
1.0.1 is a pure Python wheel and does not build its optional Face3D C++ extension by
default. Older InsightFace releases may require Microsoft C++ Build Tools.

## Model cache and license

The official InsightFace mechanism downloads `buffalo_l` once beneath:

```text
D:\VisionScribe-AI-Phase-1\models\models\buffalo_l
```

`FACE_MODEL_ROOT` and `FACE_MODEL_NAME` are configurable. The application directly loads
only the SCRFD detector file (`det_10g.onnx`). It does not load recognition, gender/age,
or landmark models contained in the pack.

InsightFace library code is MIT licensed, but its provided pretrained model packs are
restricted to non-commercial research use. Confirm licensing before commercial use.

## Configuration

```env
FRAME_SAMPLE_INTERVAL_SECONDS=1.0
MAX_SAMPLED_FRAMES=600
FACE_DETECTION_THRESHOLD=0.50
FACE_DETECTION_SIZE=640
FACE_MODEL_NAME=buffalo_l
FACE_MODEL_ROOT=models
FACE_DEVICE=auto
```

`FACE_DEVICE` accepts `auto`, `cuda`, or `cpu`. Even when `cuda` is requested, the
application safely uses CPU if CUDA cannot become active.

## CUDA verification

```cmd
nvidia-smi
python --version
python -c "import onnxruntime as ort; print(ort.get_available_providers())"
```

Provider listing alone is not proof that a model session can load CUDA. This project also
checks `detector.session.get_providers()` after SCRFD initialization.

On the verified development machine, ONNX Runtime advertises CUDA, but the model session
falls back to CPU because `cublasLt64_13.dll` is missing. ONNX Runtime 1.27 requires CUDA
13.x and cuDNN 9.x. CPU detection remains fully operational. Install matching CUDA/cuDNN
runtime DLLs and verify the active model session before claiming GPU acceleration; the
NVIDIA driver or `nvidia-smi` alone is insufficient.

CPU-only alternative: replace `onnxruntime-gpu` with `onnxruntime` in a separate
environment and set `FACE_DEVICE=cpu`. Never install both runtime packages together.

## FFmpeg and FFprobe

Phase 2 still requires `ffprobe`. Configure `FFPROBE_BINARY` or place the portable binary
at:

```text
D:\VisionScribe-AI-Phase-1\tools\ffmpeg\bin\ffprobe.exe
```

System-wide alternative:

```cmd
winget install --id Gyan.FFmpeg
```

## API result

`GET /api/jobs/{job_id}` returns, among other Phase 2 metadata:

```json
{
  "job_id": "job-id",
  "status": "completed",
  "progress": 100,
  "current_stage": "Face detection complete — ready for transcription in Phase 4",
  "face_detected": true,
  "maximum_face_count": 2,
  "sampled_frame_count": 30,
  "average_detection_confidence": 0.87,
  "best_detection_confidence": 0.96,
  "inference_device": "CPU",
  "detected_language": null,
  "transcript_json": null,
  "error_message": null
}
```

Detection confidence only describes detector confidence that a bounding box contains a
face-like region. It is never identity, liveness, authenticity, or verification confidence.

## Run and verify

```powershell
cd D:\VisionScribe-AI-Phase-1
.\.venv\Scripts\Activate.ps1
$env:VISIONSCRIBE_DEBUG = "false"
python -m uvicorn app.main:app --reload
```

Open <http://127.0.0.1:8000>.

```powershell
pytest -q
ruff check app tests
python -m compileall app
node --check static/js/app.js
```

## Troubleshooting

- `FFprobe is unavailable`: set `FFPROBE_BINARY` to a working executable.
- `Face detector model could not be loaded`: verify the model cache and its license.
- CUDA is listed but results say CPU: CUDA/cuDNN DLLs could not activate in the real model
  session; CPU fallback is expected.
- `No video frames could be decoded`: confirm OpenCV supports the video's codec.
- OpenCV DLL import errors: install the current Microsoft Visual C++ Redistributable.

## Privacy limitations

- Process only content you own or are authorized to use.
- No sampled frame, face crop, coordinate, embedding, biometric template, or identity is
  stored.
- Frames live only in memory for the minimum inference duration.
- Temporary videos are deleted after success and failure.
- Identity always remains Unknown.
- Detection does not prove identity, liveness, authenticity, or authorization.

## Phase 4 preview

Phase 4 will add speech extraction and timestamped transcription. It is not implemented
and must not start without confirmation.

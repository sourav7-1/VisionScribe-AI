import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import PROJECT_ROOT, get_settings
from app.database import initialize_database
from app.routes.health import router as health_router
from app.routes.jobs import router as jobs_router

settings = get_settings()
logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))
templates = Jinja2Templates(directory=PROJECT_ROOT / "templates")


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings.temp_dir.mkdir(parents=True, exist_ok=True)
    initialize_database()
    yield


app = FastAPI(
    title=settings.app_name,
    version="0.4.0",
    description="Face-presence detection and timestamped video transcription.",
    debug=settings.debug,
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["*"],
)
app.mount("/static", StaticFiles(directory=PROJECT_ROOT / "static"), name="static")
app.include_router(health_router)
app.include_router(jobs_router)


@app.exception_handler(HTTPException)
async def structured_http_error(_: Request, exc: HTTPException) -> JSONResponse:
    if isinstance(exc.detail, dict) and "error" in exc.detail:
        return JSONResponse(status_code=exc.status_code, content=exc.detail)
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": "http_error", "message": str(exc.detail), "details": {}}},
    )


@app.exception_handler(RequestValidationError)
async def structured_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    is_url_request = any(item.get("loc", [None])[-1] == "url" for item in exc.errors())
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "invalid_url" if is_url_request else "invalid_request",
                "message": "Enter a valid public video URL."
                if is_url_request
                else "The request is invalid.",
                "details": {},
            }
        },
    )


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def dashboard(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"app_name": settings.app_name},
    )

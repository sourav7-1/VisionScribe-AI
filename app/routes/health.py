from datetime import UTC, datetime

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import text

from app.config import get_settings
from app.database import engine

router = APIRouter(prefix="/api", tags=["system"])


class HealthResponse(BaseModel):
    status: str
    application: str
    database: str
    timestamp: datetime


@router.get("/health", response_model=HealthResponse)
def health_check() -> HealthResponse:
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))

    return HealthResponse(
        status="healthy",
        application=get_settings().app_name,
        database="connected",
        timestamp=datetime.now(UTC),
    )

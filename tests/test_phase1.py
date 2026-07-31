from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import inspect

from app.database import engine
from app.main import app


def test_health_endpoint_and_database() -> None:
    with TestClient(app) as client:
        response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json()["status"] == "healthy"
    assert response.json()["database"] == "connected"
    assert "processing_jobs" in inspect(engine).get_table_names()


def test_dashboard_shell() -> None:
    with TestClient(app) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert "VisionScribe" in response.text
    assert "Identity" in response.text
    assert "Unknown" in response.text


def teardown_module() -> None:
    engine.dispose()
    Path("test_visionscribe.db").unlink(missing_ok=True)

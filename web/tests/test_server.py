"""Tests for the asset-forge web server."""
import pytest


def test_health():
    from fastapi.testclient import TestClient
    from web.server import app
    client = TestClient(app)
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_generate_requires_prompt():
    from fastapi.testclient import TestClient
    from web.server import app
    client = TestClient(app)
    # Missing prompt field
    response = client.post("/api/generate", data={"actions": "", "variants": "1", "backend": "gemini"})
    assert response.status_code in (400, 422)


def test_generate_rejects_invalid_backend():
    from fastapi.testclient import TestClient
    from web.server import app
    client = TestClient(app)
    response = client.post(
        "/api/generate",
        data={"prompt": "a test character", "actions": "", "variants": "1", "backend": "invalid"},
    )
    assert response.status_code == 400


def test_preview_returns_404_for_missing_file():
    from fastapi.testclient import TestClient
    from web.server import app
    client = TestClient(app)
    response = client.get("/preview/nonexistent.png")
    assert response.status_code == 404

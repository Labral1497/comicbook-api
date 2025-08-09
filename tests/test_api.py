# tests/test_api.py
import json
from pathlib import Path
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.api import app  # your FastAPI app module
import app.main as main


@pytest.fixture
def client(monkeypatch):
    # Patch OpenAI client to avoid real calls
    from test_main import FakeOpenAIClient, _fake_png_b64
    monkeypatch.setattr(main, "_client", FakeOpenAIClient(_fake_png_b64()))
    return TestClient(app)


def _tiny_png_bytes():
    im = Image.new("RGB", (16, 16), (10, 20, 30))
    buf = BytesIO()
    im.save(buf, format="PNG")
    buf.seek(0)
    return buf.getvalue()


def test_generate_pdf_without_image(client, tmp_path, monkeypatch):
    # Ensure BASE_OUTPUT_DIR goes into tmp_path for the test
    monkeypatch.setenv("PYTHONPATH", str(tmp_path))
    pages = [
        {"id": 1, "title": "T1", "panels": ["A", "B", "C", "D"]},
        {"id": 2, "title": "T2", "panels": ["E", "F", "G", "H"]},
    ]
    data = {
        "comic_title": "$uper-Cringe",
        "style": "test-style",
        "character": "test-character",
        "pages": json.dumps(pages),
        "return_pdf": "true",
    }
    resp = client.post("/generate", data=data)
    assert resp.status_code == 200
    # returned a PDF file
    assert resp.headers["content-type"] == "application/pdf"


def test_generate_zip_with_image(client):
    pages = [
        {"id": 1, "title": "T1", "panels": ["A", "B", "C", "D"]},
    ]
    files = {
        "image": ("ref.png", _tiny_png_bytes(), "image/png"),
    }
    data = {
        "comic_title": "Demo",
        "style": "s",
        "character": "c",
        "pages": json.dumps(pages),
        "return_pdf": "false",
    }
    resp = client.post("/generate", data=data, files=files)
    assert resp.status_code == 200
    # returned a zip
    assert resp.headers["content-type"] == "application/zip"

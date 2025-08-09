# tests/test_api.py
import json
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.api import app
import app.main as main


@pytest.fixture
def client(monkeypatch):
    # Patch OpenAI client to avoid real calls
    from tests.test_main import FakeOpenAIClient, _fake_png_b64
    monkeypatch.setattr(main, "_client", FakeOpenAIClient(_fake_png_b64()))
    return TestClient(app)


def _tiny_png_bytes():
    im = Image.new("RGB", (16, 16), (10, 20, 30))
    buf = BytesIO()
    im.save(buf, format="PNG")
    buf.seek(0)
    return buf.getvalue()


def test_generate_pdf_without_image(client):
    payload = {
        "comic_title": "$uper-Cringe",
        "style": "test-style",
        "character": "test-character",
        "pages": [
            {"id": 1, "title": "T1", "panels": ["A", "B", "C", "D"]},
            {"id": 2, "title": "T2", "panels": ["E", "F", "G", "H"]},
        ],
        "return_pdf": True,
    }
    # Send as multipart with a single 'payload' string field
    resp = client.post(
        "/generate",
        data={"payload": json.dumps(payload)},  # Form(...) expects a string
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/pdf")


def test_generate_zip_with_image(client):
    payload = {
        "comic_title": "Demo",
        "style": "s",
        "character": "c",
        "pages": [
            {"id": 1, "title": "T1", "panels": ["A", "B", "C", "D"]},
        ],
        "return_pdf": False,
    }
    files = {
        "image": ("ref.png", _tiny_png_bytes(), "image/png"),
    }
    resp = client.post(
        "/generate",
        data={"payload": json.dumps(payload)},
        files=files,
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/zip")

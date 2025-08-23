# tests/test_generate_comic_endpoint.py
import io
import json
import base64

def test_generate_comic_multipart_pdf(client, tmp_path):
    # Build payload for ComicRequest
    payload = {
        "comic_title": "Test Comic",
        "style": "Pixar 3D animated cartoon style",
        "character": "Funny plumber; expressive eyes.",
        "pages": [
            {"id": 1, "title": "Intro", "panels": ["Wide shot", "Close-up", "Action pose", "Reaction face"]}
        ],
        "return_pdf": True
    }
    files = {
        "payload": (None, json.dumps(payload), "application/json"),
        # optional: upload image file
        "image": ("ref.png", base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4nGNgYAAAAAMAASsJTYQAAAAASUVORK5CYII="),
            "image/png")
    }
    r = client.post("/api/v1/generate/comic", files=files)
    assert r.status_code == 200
    # Should be a PDF response
    assert r.headers["content-type"] == "application/pdf"

def test_generate_comic_multipart_zip(client):
    payload = {
        "comic_title": "Test Comic",
        "style": "Pixar 3D animated cartoon style",
        "character": "Funny plumber; expressive eyes.",
        "pages": [
            {"id": 1, "title": "Intro", "panels": ["Wide", "Close", "Action", "Reaction"]}
        ],
        "return_pdf": False
    }
    files = {"payload": (None, json.dumps(payload), "application/json")}
    r = client.post("/api/v1/generate/comic", files=files)
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/zip"

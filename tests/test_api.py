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

# --------------------
# /generate images tests
# --------------------

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
        "/api/v1/generate/comic/pages",
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
        "/api/v1/generate/comic/pages",
        data={"payload": json.dumps(payload)},
        files=files,
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/zip")

# --------------------
# /story-ideas tests
# --------------------

def _fake_story_ideas_response_json():
    return json.dumps({
        "ideas": [
            {"title": "Cringe Crusader", "synopsis": "A hero so awkward, villains die laughing.", "character_description": "30s hero", "cover_art_description": "futuristic"},
            {"title": "Monetize This!", "synopsis": "Profit meets parody in a caped crusade for cash.", "character_description": "30s hero", "cover_art_description": "futuristic"},
            {"title": "Dubai Nights", "synopsis": "Shirtless dances meet high-rise heroics.", "character_description": "30s hero", "cover_art_description": "futuristic"}
        ]
    })


class _FakeChatCompletions:
    def __init__(self, content: str):
        self._content = content

    def create(self, **kwargs):
        # Mimic shape: resp.choices[0].message.content
        class _Msg: pass
        class _Choice: pass
        class _Resp: pass
        m = _Msg(); m.content = self._content
        c = _Choice(); c.message = m
        r = _Resp(); r.choices = [c]
        return r


class _FakeTextClient:
    def __init__(self, content: str):
        # Expose .chat.completions.create(...)
        class _Chat: pass
        self.chat = _Chat()
        self.chat.completions = _FakeChatCompletions(content)


def test_story_ideas_success(client, monkeypatch):
    # Patch the text client used inside app.main.story_ideas
    monkeypatch.setattr(main, "_text_client", _FakeTextClient(_fake_story_ideas_response_json()))
    payload = {
        "name": "Yaron Shamai",
        "theme": "Superhero",
        "job": "Monetization",
        "dream": "Become a pornstar",
        "origin": "Israel",
        "hobby": "Dancing without a shirt in the rain",
        "catchphrase": "it is not me! its my dark side!",
        "super_skill": "to make the cringe go away",
        "favorite_place": "Dubai",
        "taste_in_women": "Blonde in bikini"
    }
    resp = client.post("/api/v1/generate/comic/ideas", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert "ideas" in data
    assert isinstance(data["ideas"], list)
    assert len(data["ideas"]) == 3
    assert all("title" in i and "synopsis" in i for i in data["ideas"])


def test_story_ideas_malformed_model_output_returns_empty_list(client, monkeypatch):
    # Return non-JSON to trigger the fallback path (empty ideas)
    monkeypatch.setattr(main, "_text_client", _FakeTextClient("NOT JSON AT ALL"))
    payload = {
        "name": "Yaron Shamai",
        "theme": "Superhero",
        "job": "Monetization",
        "dream": "Become a pornstar",
        "origin": "Israel",
        "hobby": "Dancing without a shirt in the rain",
        "catchphrase": "it is not me! its my dark side!",
        "super_skill": "to make the cringe go away",
        "favorite_place": "Dubai",
        "taste_in_women": "Blonde in bikini"
    }
    resp = client.post("/api/v1/generate/comic/ideas", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert "ideas" in data
    assert data["ideas"] == []

# --------------------
# /generate/comic-cover tests
# --------------------

def _fake_img_b64_png():
    # Reuse tiny PNG trick from other tests if needed; but your client fixture
    # already patches main._client to return a tiny PNG via FakeOpenAIClient.
    return True  # placeholder; the fixture handles image generation


def test_generate_comic_cover_without_image(client):
    payload = {
        "cover_art_description": "Yaron leaps from a Dubai rooftop, neon skyline blazing, wind tearing his scarf.",
        "user_theme": "Synthwave Superhero"
    }
    resp = client.post(
        "/api/v1/generate/comic/cover",
        data={"payload": json.dumps(payload)},
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("image/png")


def test_generate_comic_cover_with_image(client):
    payload = {
        "cover_art_description": "Close-up hero pose, lightning splitting the night over Dubai Marina.",
        "user_theme": "Neon Noir"
    }
    # tiny image file
    img = Image.new("RGB", (16, 16), (5, 10, 15))
    buf = BytesIO(); img.save(buf, format="PNG"); buf.seek(0)

    resp = client.post(
        "/api/v1/generate/comic/cover",
        data={"payload": json.dumps(payload)},
        files={"image": ("ref.png", buf.getvalue(), "image/png")},
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("image/png")

# --------------------
# /generate/full-script tests
# --------------------

def _full_script_ok_json():
    return json.dumps({
        "title": "Good Title",
        "tagline": "Good Tagline",
        "cover_art_description": "Poster-like cover with cinematic lighting and bold colors.",
        "pages": [
            {
                "page_number": 1,
                "panels": [
                    {
                        "panel_number": 1,
                        "art_description": "Wide shot of city; hero enters; dynamic pose.",
                        "dialogue": "Roey: 'Alright, let's do this!'",
                        "narration": "",
                        "sfx": "SWISH!"
                    }
                ]
            }
        ]
    }, ensure_ascii=False)

def _full_script_bad_schema_json():
    # Missing required fields and wrong types -> should fail schema validation
    return json.dumps({
        "tagline": "Oops",
        "cover_art_description": 123,   # wrong type
        "pages": "not-a-list"          # wrong type
    }, ensure_ascii=False)

async def _mock_full_script_llm_ok(*args, **kwargs):
    return _full_script_ok_json()

async def _mock_full_script_llm_bad(_prompt: str) -> str:
    return _full_script_bad_schema_json()

def _full_script_payload():
    return {
        "chosen_story_idea": "Founder tries to launch an AI comics platform, chaos ensues.",
        "user_name": "Roey",
        "user_gender": "Male",
        "character_description": "30s, techwear hoodie, expressive eyebrows, short dark hair.",
        "page_count": 3,
        "user_theme": "Tech entrepreneur comedy",
        "user_answers_list": ["self-deprecating humor", "debugging mishaps"]
    }

def test_full_script_success(client, monkeypatch):
    # Patch LLM call inside app.main
    monkeypatch.setattr(main, "call_llm_return_json_string", _mock_full_script_llm_ok)
    # monkeypatch.setattr(main, "call_llm_return_json_string",lambda *a, **k: _full_script_ok_json())

    resp = client.post("/api/v1/generate/comic/script", json=_full_script_payload())
    assert resp.status_code == 200, resp.text

    data = resp.json()
    assert set(data.keys()) == {"title", "tagline", "cover_art_description", "pages"}
    assert isinstance(data["pages"], list) and len(data["pages"]) >= 1
    assert data["pages"][0]["page_number"] == 1
    assert isinstance(data["pages"][0]["panels"], list) and len(data["pages"][0]["panels"]) >= 1
    assert data["pages"][0]["panels"][0]["panel_number"] == 1
    assert "art_description" in data["pages"][0]["panels"][0]

def test_full_script_schema_error_from_llm(client, monkeypatch):
    # Return malformed JSON (schema-wise) to trigger 422 from API
    monkeypatch.setattr(main, "call_llm_return_json_string", _mock_full_script_llm_bad)

    resp = client.post("/api/v1/generate/comic/script", json=_full_script_payload())
    assert resp.status_code == 422
    detail = resp.json().get("detail", "")
    # Your API raises HTTPException(422, f"Schema validation failed: {ve.errors()}")
    assert "Schema validation failed" in str(detail)

def test_full_script_invalid_request_body(client):
    # page_count <= 0 -> request validation should fail before hitting the LLM
    bad = _full_script_payload()
    bad["page_count"] = 0
    resp = client.post("/api/v1/generate/comic/script", json=bad)
    assert resp.status_code == 422

# tests/conftest.py
import io
import json
import base64
import types
import pytest
from fastapi.testclient import TestClient

# Import the app instance
from app.main import app

# -------- Test client --------
@pytest.fixture(scope="session")
def client():
    return TestClient(app)

# -------- Utilities --------
def _tiny_png_base64() -> str:
    # 1x1 transparent PNG
    return (
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4nGNg"
        "YAAAAAMAASsJTYQAAAAASUVORK5CYII="
    )

# -------- Mocks for OpenAI --------
class _MockImageData:
    def __init__(self, b64_json):
        self.b64_json = b64_json

class _MockImagesResponse:
    def __init__(self, b64_json):
        self.data = [ _MockImageData(b64_json) ]

class _MockMessage:
    def __init__(self, content: str):
        self.content = content

class _MockChoice:
    def __init__(self, content: str):
        self.message = _MockMessage(content)

class _MockChatResponse:
    def __init__(self, content: str):
        self.choices = [ _MockChoice(content) ]

@pytest.fixture(autouse=True)
def mock_openai(monkeypatch):
    """
    Auto-mock OpenAI client everywhere so tests don't hit the network.
    """
    from app.lib import openai_client

    # Mock images.generate -> returns a 1x1 PNG base64
    def _fake_images_generate(model, prompt, size, n):
        return _MockImagesResponse(_tiny_png_base64())

    # Mock chat.completions.create -> return fixed JSON depending on prompt "mode"
    def _fake_chat_create(model, temperature, messages, **kwargs):
        system = messages[0]["content"]
        user   = messages[1]["content"]

        # naive routing by keywords in system/user
        if "JSON array of three objects" in system:
            # story ideas response (array)
            payload = json.dumps([
                {"title": "Idea 1", "synopsis": "Funny pitch 1."},
                {"title": "Idea 2", "synopsis": "Funny pitch 2."},
                {"title": "Idea 3", "synopsis": "Funny pitch 3."},
            ])
        elif "'title', 'tagline', 'cover_art_description', and 'story_summary'" in system:
            # cover script response (object)
            payload = json.dumps({
                "title": "Mocked Cover Title",
                "tagline": "Mocked Tagline",
                "cover_art_description": "Mocked cover art description.",
                "story_summary": "Mocked 3–8 sentence story summary."
            })
        elif "json_schema" in kwargs.get("response_format", {}):
            # full script structured output: minimal valid shape
            payload = json.dumps({
                "title": "Mocked Full Title",
                "tagline": "Mocked Full Tagline",
                "cover_art_description": "Mocked cover.",
                "pages": [
                    {
                        "page_number": 1,
                        "panels": [
                            {
                                "panel_number": 1,
                                "art_description": "Wide shot of city.",
                                "dialogue": "Hero: 'Hi'",
                                "narration": "",
                                "sfx": "WHOOOSH"
                            }
                        ]
                    }
                ]
            })
        else:
            payload = json.dumps({"ok": True})
        return _MockChatResponse(payload)

    # Patch the client methods
    monkeypatch.setattr(openai_client.client.images, "generate", _fake_images_generate)
    monkeypatch.setattr(openai_client.client.chat.completions, "create", _fake_chat_create)
    yield

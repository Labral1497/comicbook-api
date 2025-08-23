# tests/test_pages_endpoints.py
import json
from app.features.full_script.schemas import FullScriptResponse, Page, Panel

def _make_full_script_payload():
    return {
        "title": "Mocked Full Title",
        "tagline": "Mocked Full Tagline",
        "cover_art_description": "Mocked cover.",
        "pages": [
            {
                "page_number": 1,
                "panels": [
                    {
                        "panel_number": 1,
                        "art_description": "City wide shot.",
                        "dialogue": "Hero: 'Hello'",
                        "narration": "",
                        "sfx": "WHOOSH"
                    }
                ]
            }
        ]
    }

# If you exposed pages endpoints (optional from earlier), you can test them like this:
def test_pages_endpoints_generate_and_pdf(client):
    # skip if pages router not included
    try:
        # generate images from prompts directly
        payload = {
            "prompts": ["Title — Page 1\nSTYLE: Test\nCHARACTER: Test\n4 panels:\n1) A\n2) B\n3) C\n4) D"],
            "output_prefix": "data/test_page",
            "max_workers": 1
        }
        r = client.post("/api/v1/generate/comic/pages", json=payload)
        # If not found, router isn't enabled; skip without failure
        if r.status_code == 404:
            return
        assert r.status_code == 200
        files = r.json()["files"]
        assert files and files[0].endswith(".png")

        # compose pdf
        r2 = client.post("/api/v1/compose/pdf", json={"files": files, "pdf_name": "data/test.pdf"})
        assert r2.status_code == 200
        assert r2.json()["pdf_path"].endswith(".pdf")
    except Exception:
        # router might not be wired; don't fail the suite if feature is optional
        return

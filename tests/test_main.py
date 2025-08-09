# tests/test_main.py
import base64
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

import app.main as main


def _fake_png_b64(w=64, h=64):
    """Return a tiny in-memory PNG as base64 for mocking."""
    im = Image.new("RGB", (w, h), (123, 45, 67))
    buf = BytesIO()
    im.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


class FakeOpenAIImagesGenerateResponse:
    def __init__(self, b64):
        class _D:  # minimal shape: resp.data[0].b64_json
            def __init__(self, b):
                self.b64_json = b
        self.data = [_D(b64)]


class FakeOpenAIImages:
    def __init__(self, b64):
        self._b64 = b64
    def generate(self, **kwargs):
        return FakeOpenAIImagesGenerateResponse(self._b64)


class FakeOpenAIClient:
    def __init__(self, b64):
        self.images = FakeOpenAIImages(b64)


@pytest.fixture
def fake_client(monkeypatch):
    """Patch main._client with a fake OpenAI client returning a tiny PNG."""
    fake = FakeOpenAIClient(_fake_png_b64())
    monkeypatch.setattr(main, "_client", fake)
    return fake


def test_generate_page_creates_file(tmp_path, fake_client):
    out_prefix = tmp_path / "page"
    fname = main.generate_page(
        page_idx=0,
        prompt="Test prompt",
        output_filename_prefix=str(out_prefix),
        model="dummy",
        size="1024x1024",
        retries=1,
    )
    assert fname is not None
    p = Path(fname)
    assert p.exists()
    assert p.name == "page-1.png"
    assert p.suffix == ".png"


def test_generate_pages_creates_multiple_files(tmp_path, fake_client):
    prompts = ["p1", "p2", "p3"]
    out_prefix = tmp_path / "page"
    files = main.generate_pages(
        prompts,
        max_workers=2,
        output_prefix=str(out_prefix),
        model="dummy",
        size="1024x1024",
    )
    assert len(files) == 3
    for i, f in enumerate(files, start=1):
        p = Path(f)
        assert p.exists()
        assert p.name == f"page-{i}.png"


def test_make_pdf_builds_pdf(tmp_path, fake_client):
    # first create two images
    prompts = ["p1", "p2"]
    out_prefix = tmp_path / "page"
    files = main.generate_pages(prompts, output_prefix=str(out_prefix))
    # now build PDF
    pdf_path = tmp_path / "out.pdf"
    got = main.make_pdf(files, pdf_name=str(pdf_path))
    assert got == str(pdf_path)
    assert pdf_path.exists()
    # sanity: file not empty
    assert pdf_path.stat().st_size > 0


def test_generate_page_retries_and_returns_none_on_failure(monkeypatch, tmp_path):
    # make client raise Exception every time
    class FailingImages:
        def generate(self, **kwargs):
            raise RuntimeError("boom")
    class FailingClient:
        images = FailingImages()

    monkeypatch.setattr(main, "_client", FailingClient())
    out_prefix = tmp_path / "page"
    fname = main.generate_page(
        page_idx=0,
        prompt="x",
        output_filename_prefix=str(out_prefix),
        retries=2,
        delay=0.01,
    )
    assert fname is None

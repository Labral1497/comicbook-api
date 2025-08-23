# tests/test_cover_service.py
import os
from app.features.cover.schemas import GenerateCoverRequest
from app.features.cover.service import generate_comic_cover

def test_generate_comic_cover(tmp_path):
    req = GenerateCoverRequest(
        title="The Mock Title",
        tagline="The Mock Tagline",
        cover_art_description="Hero pose; neon skyline.",
        user_theme="Pixar 3D animated cartoon style",
        return_mode="inline",
        image_base64="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4nGNgYAAAAAMAASsJTYQAAAAASUVORK5CYII="
    )
    out_path = os.path.join(tmp_path, "cover.png")
    path = generate_comic_cover(req, out_path=out_path)
    assert os.path.exists(path)
    assert os.path.getsize(path) > 0

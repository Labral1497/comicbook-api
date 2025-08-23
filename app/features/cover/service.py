# app/features/cover/service.py
import base64
import os
from app.config import config
from app.lib.openai_client import client
from .schemas import GenerateCoverRequest
from .prompt import build_cover_prompt

def _maybe_decode_image_to_path(image_base64: str | None) -> str | None:
    if not image_base64:
        return None
    if image_base64.startswith("data:"):
        _, b64 = image_base64.split(",", 1)
    else:
        b64 = image_base64
    os.makedirs("data", exist_ok=True)
    path = "data/ref_image.jpg"
    with open(path, "wb") as f:
        f.write(base64.b64decode(b64))
    return path

def generate_comic_cover(req: GenerateCoverRequest, *, out_path: str) -> str:
    image_ref_path = _maybe_decode_image_to_path(req.image_base64)
    prompt = build_cover_prompt(
        title=req.title,
        tagline=req.tagline,
        cover_art_description=req.cover_art_description,
        user_theme=req.user_theme,
        image_ref_path=image_ref_path,
    )
    resp = client.images.generate(model=config.openai_image_model, prompt=prompt, size=config.image_size, n=1)
    b64 = resp.data[0].b64_json
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "wb") as f:
        f.write(base64.b64decode(b64))
    return out_path

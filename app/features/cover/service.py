# app/features/cover/service.py
import base64
import os

from fastapi import HTTPException
from app.config import config
from app.lib.gcs_inventory import _decode_image_b64
from app.lib.openai_client import client
from .schemas import GenerateCoverRequest
from .prompt import build_cover_prompt
from app.logger import get_logger

log = get_logger(__name__)

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

def generate_comic_cover(req: GenerateCoverRequest, *, out_path: str, workdir: str) -> str:
    # Optional image save
    ref_path = None
    if req.image_base64:
        try:
            data, ctype = _decode_image_b64(req.image_base64)
        except Exception as e:
            raise HTTPException(400, f"Invalid image_base64: {e}")
        if ctype not in {"image/png", "image/jpeg"}:
            raise HTTPException(400, "image must be PNG or JPEG")
        ref_path = os.path.join(workdir, "cover_ref.png")
        # Always normalize to PNG for downstream tools
        with open(ref_path, "wb") as f:
            f.write(data)

    prompt = build_cover_prompt(
        title=req.title,
        tagline=req.tagline,
        cover_art_description=req.cover_art_description,
        user_theme=req.user_theme,
        image_ref_path=ref_path,
    )
    log.debug(f"cover prompt is: {prompt}")
    resp = client.images.generate(model=config.openai_image_model, prompt=prompt, size=config.image_size, n=1)
    b64 = resp.data[0].b64_json
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "wb") as f:
        f.write(base64.b64decode(b64))
    return out_path

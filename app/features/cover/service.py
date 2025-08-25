# app/features/cover/service.py
import base64
import os

from fastapi import HTTPException
from app.config import config
from app.lib.imaging import maybe_decode_image_to_path
from app.lib.openai_client import client
from .schemas import GenerateCoverRequest
from .prompt import build_cover_prompt
from app.logger import get_logger

log = get_logger(__name__)

def generate_comic_cover(req: GenerateCoverRequest, *, out_path: str, workdir: str) -> str:
    # Optional image save
    ref_path = maybe_decode_image_to_path(req.image_base64, workdir)

    prompt = build_cover_prompt(
        title=req.title,
        tagline=req.tagline,
        cover_art_description=req.cover_art_description,
        user_theme=req.user_theme,
    )
    log.debug(f"cover prompt is: {prompt}")
    if ref_path:
        resp = client.images.edit(
            model=config.openai_image_model,
            prompt=prompt,
            size=config.image_size,
            n=1,
            image=open(ref_path, "rb"),
        )
    else:
        # No reference: plain generate
        resp = client.images.generate(
            model=config.openai_image_model,
            prompt=prompt,
            size=config.image_size,
            n=1,
        )
    b64 = resp.data[0].b64_json
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "wb") as f:
        f.write(base64.b64decode(b64))
    return out_path

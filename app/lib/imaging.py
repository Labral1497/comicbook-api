# app/lib/imaging.py
import base64
import concurrent.futures
import time
import os
from typing import List, Optional

from fastapi import HTTPException
from app.config import config
from app import logger
from app.lib.gcs_inventory import _DATAURL_RE
from app.lib.openai_client import client as _client

log = logger.get_logger(__name__)

def decode_image_b64(image_b64: str) -> tuple[bytes, str]:
    """
    Returns (bytes, content_type). Supports 'data:image/png;base64,...' or raw base64.
    Only PNG and JPEG are accepted.
    """
    if not image_b64:
        raise ValueError("empty base64")
    m = _DATAURL_RE.match(image_b64.strip())
    if m:
        content_type = m.group(1).lower()
        payload = m.group(2)
        data = base64.b64decode(payload)
    else:
        # Try raw base64; sniff magic to decide content type
        data = base64.b64decode(image_b64.strip())
        if data.startswith(b"\x89PNG\r\n\x1a\n"):
            content_type = "image/png"
        elif data.startswith(b"\xff\xd8"):
            content_type = "image/jpeg"
        else:
            raise ValueError("Unsupported image format; only PNG or JPEG")
    return data, content_type

def maybe_decode_image_to_path(image_base64: str | None, workdir: str) -> str | None:
    ref_path = None
    if image_base64:
        try:
            data, ctype = decode_image_b64(image_base64)
        except Exception as e:
            raise HTTPException(400, f"Invalid image_base64: {e}")
        if ctype not in {"image/png", "image/jpeg"}:
            raise HTTPException(400, "image must be PNG or JPEG")
        ref_path = os.path.join(workdir, "cover_ref.png")
        # Always normalize to PNG for downstream tools
        with open(ref_path, "wb") as f:
            f.write(data)
    return ref_path

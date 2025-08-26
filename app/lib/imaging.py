from __future__ import annotations
import base64
import os
import re
import shutil
import uuid
from typing import Optional

from fastapi import HTTPException
from app.config import config
from app import logger
from app.lib.gcs_inventory import _DATAURL_RE
from app.lib.openai_client import client as _client

log = logger.get_logger(__name__)

def _is_data_url(s: str) -> bool:
    return s.startswith("data:image/") and ";base64," in s


def _decode_data_url_to_file(data_url: str, out_path: str) -> str:
    header, b64 = data_url.split(",", 1)
    mime = header.split(";")[0].split(":", 1)[1]  # e.g. image/png
    data = base64.b64decode(b64)
    # normalize extension by mime
    ext = ".png" if mime.endswith("png") else ".jpg"
    base, _ = os.path.splitext(out_path)
    out_file = base + ext
    with open(out_file, "wb") as f:
        f.write(data)
    return out_file


def _looks_like_raw_base64(s: str) -> bool:
    # cheap heuristic: long string, base64 charset, divisible by 4 length
    if len(s) < 200:
        return False
    if len(s) % 4 != 0:
        return False
    return re.fullmatch(r"[A-Za-z0-9+/=\s]+", s) is not None


def _decode_raw_b64_to_file(b64: str, out_path: str) -> str:
    data = base64.b64decode(b64)
    # assume PNG by default
    if not out_path.lower().endswith(".png"):
        out_path = out_path + ".png"
    with open(out_path, "wb") as f:
        f.write(data)
    return out_path


def _copy_if_exists(path_or_url: str, out_path: str) -> Optional[str]:
    """
    If it's a local path that exists, copy it into job dir for stability.
    URLs are left as-is (you can extend to download http(s)/gs:// if you want).
    """
    if os.path.exists(path_or_url):
        _, ext = os.path.splitext(path_or_url)
        if not out_path.endswith(ext):
            out_path = out_path + ext
        shutil.copy2(path_or_url, out_path)
        return out_path
    # TODO: support http(s) or gs:// download if needed
    return None


def resolve_or_download_cover_ref(image_ref: Optional[str], workdir: str) -> Optional[str]:
    """
    Turn `image_ref` into a local file path:
    - if data URL: decode to file
    - if raw base64: decode to file
    - if existing local path: copy into workdir
    - else: return None (caller will error)
    """
    if not image_ref:
        return None

    target = os.path.join(workdir, f"cover_ref_{uuid.uuid4().hex}")

    if _is_data_url(image_ref):
        return _decode_data_url_to_file(image_ref, target)

    if _looks_like_raw_base64(image_ref):
        return _decode_raw_b64_to_file(image_ref, target)

    copied = _copy_if_exists(image_ref, target)
    if copied:
        return copied

    # unsupported reference
    return None

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

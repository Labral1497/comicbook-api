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
from app.lib.gcs_inventory import _DATAURL_RE, download_gcs_object_to_file
from app.lib.openai_client import client as _client

log = logger.get_logger(__name__)

def _sniff_ext_from_bytes(data: bytes) -> str:
    # PNG
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    # JPEG
    if data.startswith(b"\xff\xd8"):
        return ".jpg"
    # GIF87a / GIF89a
    if data.startswith(b"GIF87a") or data.startswith(b"GIF89a"):
        return ".gif"
    # WEBP: RIFF....WEBP
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    return ""  # unknown

def _is_data_url(s: str) -> bool:
    # accept any data:*;base64, not only data:image/*
    return s.startswith("data:") and ";base64," in s

def _decode_data_url_to_file(data_url: str, out_path: str) -> str:
    # data:[MIME];base64,<payload>
    header, b64 = data_url.split(",", 1)
    # MIME can be image/png, application/octet-stream, etc.
    # We won’t fully trust MIME—will sniff bytes too.
    data = base64.b64decode(b64)

    # Try to decide extension by sniffing bytes first
    ext = _sniff_ext_from_bytes(data)
    if not ext:
        # If sniffing failed, map a few common mimes, else .bin
        mime = header.split(";", 1)[0].split(":", 1)[1].lower()  # e.g. image/png
        if mime.endswith("png"):
            ext = ".png"
        elif mime.endswith("jpeg") or mime.endswith("jpg"):
            ext = ".jpg"
        elif mime.endswith("gif"):
            ext = ".gif"
        elif mime.endswith("webp"):
            ext = ".webp"
        else:
            # last resort: assume PNG for octet-stream if it decodes fine?
            # safer default is .bin; choose .png if you know your producer is always PNG
            ext = ".png" if mime == "application/octet-stream" else ".bin"

    base, _ = os.path.splitext(out_path)
    out_file = base + ext
    with open(out_file, "wb") as f:
        f.write(data)
    return out_file

def _looks_like_raw_base64(s: str) -> bool:
    # keep your heuristic but allow whitespace
    if len(s) < 200:
        return False
    # base64 payloads often not divisible by 4 due to stripping; be more forgiving
    if not re.fullmatch(r"[A-Za-z0-9+/=\s]+", s):
        return False
    return True

def _decode_raw_b64_to_file(b64: str, out_path: str) -> str:
    data = base64.b64decode(b64)
    ext = _sniff_ext_from_bytes(data) or ".png"  # default to PNG if unknown
    if not out_path.lower().endswith(ext):
        out_path = out_path + ext
    with open(out_path, "wb") as f:
        f.write(data)
    return out_path

def _copy_if_exists(path_or_url: str, out_path: str) -> Optional[str]:
    if os.path.exists(path_or_url):
        _, ext = os.path.splitext(path_or_url)
        if ext and not out_path.endswith(ext):
            out_path = out_path + ext
        shutil.copy2(path_or_url, out_path)
        return out_path
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

_DATA_URL_RE = re.compile(r"^data:image/[\w+.-]+;base64,(?P<b64>.+)$", re.IGNORECASE | re.DOTALL)

def resolve_cover_ref_b64_or_gcs(
    image_b64: Optional[str],
    *,
    job_id: str,
    workdir: str,
    bucket: Optional[str] = None,
) -> Optional[str]:
    """
    1) If `image_b64` is provided, decode (supports raw b64 or data URL) -> save -> return path.
    2) Else (or if decode fails), fetch gs://{bucket}/jobs/{job_id}/cove.png -> save -> return path.
    Returns None if neither path succeeds.
    """
    os.makedirs(workdir, exist_ok=True)

    # ---------- Try base64 from request ----------
    if image_b64:
        try:
            m = _DATA_URL_RE.match(image_b64.strip())
            b64 = m.group("b64") if m else image_b64.strip()
            # Normalize whitespace and padding
            b64 = "".join(b64.split())
            missing_padding = (-len(b64)) % 4
            if missing_padding:
                b64 += "=" * missing_padding

            raw = base64.b64decode(b64, validate=False)
            if raw:
                out = os.path.join(workdir, f"cover_ref_{uuid.uuid4().hex}.png")
                with open(out, "wb") as f:
                    f.write(raw)
                return out
        except Exception as e:
            log.warning("Failed to decode cover image base64; will try GCS fallback: %s", e)

    # ---------- Fallback: GCS jobs/{job_id}/cove.png ----------
    bucket = bucket or getattr(config, "gcs_bucket", None)
    if not bucket:
        log.error("No GCS bucket configured (config.gcs_bucket missing) and no bucket argument provided.")
        return None

    gs_uri = f"gs://{bucket}/jobs/{job_id}/cover.png"
    out = os.path.join(workdir, f"cover_ref_{uuid.uuid4().hex}.png")
    try:
        download_gcs_object_to_file(gs_uri, out)
        if os.path.exists(out) and os.path.getsize(out) > 0:
            return out
        log.error("Downloaded 0 bytes from %s", gs_uri)
    except Exception as e:
        log.error("Failed to download %s: %s", gs_uri, e)

    return None

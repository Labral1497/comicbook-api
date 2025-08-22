import base64
import os
import re
import uuid
from datetime import timedelta
from fastapi import HTTPException
from google.cloud import storage
from app.config import config
from app import logger

log = logger.get_logger(__name__)
_DATAURL_RE = re.compile(r"^data:(image/(?:png|jpeg));base64,(.*)$", re.IGNORECASE)

_storage = None
def _client():
    global _storage
    if _storage is None:
        _storage = storage.Client()
    return _storage

def _signing_creds():
    import google.auth
    from google.auth import impersonated_credentials
    # Base creds from runtime (Cloud Run SA token)
    base_creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    # If we already have a signer (e.g., SA key file), use it
    if getattr(base_creds, "signer", None):
        return base_creds
    # Otherwise impersonate a service account that CAN sign
    target_sa = os.getenv("GCS_SIGNING_SERVICE_ACCOUNT")
    if not target_sa:
        # Try to read the default SA email from metadata
        try:
            from google.auth.compute_engine import metadata
            target_sa = metadata.get_service_account_email()
        except Exception:
            pass
    if not target_sa:
        raise HTTPException(500, "Cannot sign URLs: set GCS_SIGNING_SERVICE_ACCOUNT to the service account email.")
    return impersonated_credentials.Credentials(
        source_credentials=base_creds,
        target_principal=target_sa,
        target_scopes=[
            "https://www.googleapis.com/auth/devstorage.read_write",
            "https://www.googleapis.com/auth/cloud-platform",
        ],
        lifetime=3600,
    )

def upload_to_gcs(local_path: str, *, subdir: str = "covers") -> dict:
    log.debug("koko0")
    if not config.gcs_bucket:
        log.debug("koko0.5")
        raise HTTPException(500, "GCS_BUCKET not configured")
    client = _client()
    bucket = client.bucket(config.gcs_bucket)
    object_name = f"{subdir}/{uuid.uuid4().hex}.png"
    blob = bucket.blob(object_name)
    blob.cache_control = "public, max-age=31536000"  # 1 year (tune as you like)
    blob.upload_from_filename(local_path, content_type="image/png")
    log.debug("koko1")
    signed_url = blob.generate_signed_url(
        version="v4",
        expiration=timedelta(seconds=config.signed_url_ttl),
        method="GET",
        response_disposition='inline; filename="comic_cover.png"',
        response_type="image/png",
        credentials=_signing_creds(),
    )
    log.debug("koko2")
    return {
        "bucket": config.gcs_bucket,
        "object": object_name,
        "gs_uri": f"gs://{config.gcs_bucket}/{object_name}",
        "signed_url": signed_url,
        "expires_in": config.signed_url_ttl,
        "content_type": "image/png",
    }

def _decode_image_b64(image_b64: str) -> tuple[bytes, str]:
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

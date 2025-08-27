import base64
import io
import json
import os
import re
from typing import Any, Dict, Tuple
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

def upload_to_gcs(local_path: str, *, object_name: str | None = None, subdir: str = "covers") -> dict:
    if not config.gcs_bucket:
        raise HTTPException(500, "GCS_BUCKET not configured")

    client = _client()
    bucket = client.bucket(config.gcs_bucket)

    if not object_name:
        object_name = f"{subdir}/{uuid.uuid4().hex}.png"

    blob = bucket.blob(object_name)
    blob.cache_control = "public, max-age=31536000"
    blob.upload_from_filename(local_path)

    signed_url = blob.generate_signed_url(
        version="v4",
        expiration=timedelta(seconds=config.signed_url_ttl),
        method="GET",
        response_disposition=f'inline; filename="{os.path.basename(local_path)}"',
        response_type="application/octet-stream",
        credentials=_signing_creds(),
    )

    return {
        "bucket": config.gcs_bucket,
        "object": object_name,
        "gs_uri": f"gs://{config.gcs_bucket}/{object_name}",
        "signed_url": signed_url,
        "expires_in": config.signed_url_ttl,
        "content_type": "application/octet-stream",
    }

_GS_RE = re.compile(r"^gs://([^/]+)/(.+)$")

def _parse_gs_uri(gs_uri: str) -> Tuple[str, str]:
    """
    Parse 'gs://bucket/key' -> (bucket, key)
    """
    m = _GS_RE.match(gs_uri)
    if not m:
        raise ValueError(f"Invalid gs:// URI: {gs_uri}")
    return m.group(1), m.group(2)

def upload_json_to_gcs(
    data: Any,
    *,
    object_name: str | None = None,
    subdir: str = "jobs",
    filename_hint: str = "request.json",
    cache_control: str = "no-cache",
    make_signed_url: bool = True,
) -> Dict[str, Any]:
    """
    Serialize `data` to JSON and upload to GCS. If `object_name` is None,
    a name will be generated under `subdir` as <uuid>/<filename_hint>.

    Returns a dict with bucket/object/gs_uri and optional signed_url.
    """
    if not config.gcs_bucket:
        raise HTTPException(500, "GCS_BUCKET not configured")

    client = _client()
    bucket = client.bucket(config.gcs_bucket)

    if object_name is None:
        # e.g., jobs/<uuid>/request.json
        object_name = f"{subdir}/{uuid.uuid4().hex}/{filename_hint}"

    blob = bucket.blob(object_name)
    blob.cache_control = cache_control

    # Serialize to bytes (utf-8)
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")

    blob.upload_from_file(
        io.BytesIO(payload),
        size=len(payload),
        content_type="application/json",
    )

    result: Dict[str, Any] = {
        "bucket": config.gcs_bucket,
        "object": object_name,
        "gs_uri": f"gs://{config.gcs_bucket}/{object_name}",
        "content_type": "application/json",
    }

    if make_signed_url:
        signed_url = blob.generate_signed_url(
            version="v4",
            expiration=timedelta(seconds=config.signed_url_ttl),
            method="GET",
            response_disposition=f'inline; filename="{os.path.basename(filename_hint) or "file.json"}"',
            response_type="application/json",
            credentials=_signing_creds(),
        )
        result.update({"signed_url": signed_url, "expires_in": config.signed_url_ttl})

    return result

def download_gcs_object_to_file(gs_uri: str, dest_path: str) -> None:
    """
    Download a GCS object specified as 'gs://bucket/key' to a local file path.
    Creates parent directories as needed.
    """
    bucket_name, object_name = _parse_gs_uri(gs_uri)

    client = _client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(object_name)

    os.makedirs(os.path.dirname(dest_path) or ".", exist_ok=True)
    blob.download_to_filename(dest_path)

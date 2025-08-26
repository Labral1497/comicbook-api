# app/config.py
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import List

def _env_bool(name: str, default: bool = False) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes", "on"}

def _env_csv(name: str, default: str = "*") -> List[str]:
    raw = os.getenv(name, default)
    return [x.strip() for x in raw.split(",") if x.strip()]

@dataclass(frozen=True)
class Config:
    # OpenAI
    openai_api_key: str
    openai_image_model: str
    openai_text_model: str
    image_size: str  # valid: 1024x1024, 1024x1536, 1536x1024, auto
    # API / CORS
    allowed_origins: List[str]
    # Output handling
    keep_outputs: bool
    base_output_dir: Path
    # Concurrency
    max_workers: int
    # Logging
    log_level: str
    gcs_bucket: str
    signed_url_ttl: str
    public_base_url: str

    # Cloud Tasks / GCP
    gcp_project: str
    gcp_location: str
    tasks_queue: str
    prune_pages_after_final: bool           # delete page-*.png after final upload
    prune_artifact_after_upload: bool       # delete the PDF/ZIP local file after upload
    sweep_jobs_on_startup: bool             # optional: run a sweep on app startup
    sweep_ttl_hours: int                    # delete jobs older than this if final exists

def load_config() -> Config:
    return Config(
        openai_api_key = os.getenv("OPENAI_API_KEY", ""),
        openai_image_model = os.getenv("OPENAI_IMAGE_MODEL", "gpt-image-1"),
        image_size = os.getenv("IMAGE_SIZE", "1024x1536"),
        allowed_origins = _env_csv("ALLOWED_ORIGINS", "*"),
        keep_outputs = _env_bool("KEEP_OUTPUTS", False),
        base_output_dir = (Path(__file__).resolve().parent / "output"),
        max_workers = int(os.getenv("MAX_WORKERS", "4")),
        log_level = os.getenv("LOG_LEVEL", "DEBUG"),
        gcs_bucket = os.getenv("GCS_BUCKET", "ai-comic-books-assets"),
        signed_url_ttl = int(os.getenv("GCS_SIGNED_URL_TTL", "3600")),
        openai_text_model = os.getenv("OPENAI_TEXT_MODEL", "gpt-4o-mini"),
        gcp_location = os.getenv("REGION", "us-central1"),
        gcp_project = os.getenv("PROJECT_ID", "ai-comic-books"),
        public_base_url = os.getenv("BASE_URL", "https://comics-api-y36gfn5tta-uc.a.run.app"),
        tasks_queue = os.getenv("TASKS_QUEUE", "comic-worker-queue"),
        prune_pages_after_final = _env_bool("PRUNE_PAGES_AFTER_FINAL", True),
        prune_artifact_after_upload = _env_bool("PRUNE_ARTIFACTS_AFTER_UPLOAD", False),
        sweep_jobs_on_startup = _env_bool("SWEEP_JOBS_ON_STARTUPS", False),
        sweep_ttl_hours = int(os.getenv("SWEEP_TTL_HOURS", 24))
    )

# Load once and ensure output directory exists
config = load_config()
config.base_output_dir.mkdir(parents=True, exist_ok=True)

def make_job_dir(prefix: str = "job_") -> Path:
    """
    Create a unique working directory under base_output_dir for a single request/job.
    Returns the Path to that directory.
    """
    path_str = tempfile.mkdtemp(prefix=prefix, dir=str(config.base_output_dir))
    return Path(path_str)

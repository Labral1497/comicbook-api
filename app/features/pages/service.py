# app/features/comic/service.py
import base64
import os
import random
import time
import concurrent.futures

from typing import Callable, List, Optional
from app.features.full_script.schemas import Page
from app.lib.gcs_inventory import upload_to_gcs
from app.lib.openai_client import client
from app.config import config
from app.features.pages.schemas import ComicRequest
from app.logger import get_logger
import json, threading

log = get_logger(__name__)
_manifest_lock = threading.Lock()

def mark_page_status(manifest_path: str, page_number: int, status: str, meta: dict = None):
    with _manifest_lock:
        if os.path.exists(manifest_path):
            with open(manifest_path, "r") as f:
                manifest = json.load(f)
        else:
            manifest = {"pages": {}, "final": None}

        manifest["pages"][str(page_number)] = {
            "status": status,
            "meta": meta or {}
        }

        with open(manifest_path, "w") as f:
            json.dump(manifest, f, indent=2)

def build_single_page_prompt(*, req: ComicRequest, page: Page, reference_label: str) -> str:
    page_num = page.page_number
    numbered = []
    for panel in page.panels:
        line = f"{panel.panel_number}) Art: {panel.art_description.strip()}"
        if panel.dialogue.strip():   line += f" | Dialogue: {panel.dialogue.strip()}"
        if panel.narration.strip():  line += f" | Narration: {panel.narration.strip()}"
        if panel.sfx.strip():        line += f" | SFX: {panel.sfx.strip()}"
        numbered.append(line)

    return (
        f"{req.comic_title} — Page {page_num}\n\n"
        f"**STYLE (MANDATORY FOR CONSISTENCY):**\n"
        f'The overall artistic style must match the **\"{req.style}\"** theme. '
        "Use bold, clean linework with dynamic lighting.\n\n"
        f"**REFERENCE (HIGHEST PRIORITY):**\n"
        f"The main character’s face and unique features MUST match {reference_label}. "
        "This is the most important rule.\n\n"
        "**CONTINUITY REQUIREMENTS (DO NOT BREAK):**\n"
        "- Maintain strict continuity with the referenced image: character model (face, hair, outfit), camera lens/perspective, lighting direction, color grading, environment/set dressing, props positions.\n"
        "- If the location/time changes, keep the character model identical; otherwise keep the same setting details unless the panel description explicitly changes them.\n"
        "- Keep outfit and accessories consistent unless the panel specifies a change.\n\n"
        "**PAGE-SPECIFIC PANELS (ILLUSTRATE THE FOLLOWING):**\n"
        + "\n".join(numbered)
    )

def render_pages_chained(
    *,
    req: ComicRequest,
    workdir: str,
    cover_image_ref: str,
    manifest_file: str,                 # <-- NEW (required)
    gcs_prefix: Optional[str] = None,   # <-- NEW (optional)
    on_page_done: Optional[Callable[[int, str], None]] = None,
) -> List[str]:
    """
    Sequential generation where page N uses the previous page image as reference.
    Page 1 uses the cover image as reference.
    """
    out_prefix = os.path.join(workdir, "page")
    results: List[str] = []

    prev_ref = cover_image_ref
    for idx, page in enumerate(req.pages):
        page_no = idx + 1

        # build the page-specific prompt you already have
        prompt_lines: List[str] = []
        numbered: List[str] = []
        for panel in page.panels:
            pn = panel.panel_number
            art = panel.art_description.strip()
            dialogue = panel.dialogue.strip()
            narration = panel.narration.strip()
            sfx = panel.sfx.strip()
            line = f"{pn}) Art: {art}"
            if dialogue:
                line += f" | Dialogue: {dialogue}"
            if narration:
                line += f" | Narration: {narration}"
            if sfx:
                line += f" | SFX: {sfx}"
            numbered.append(line)

        prompt = (
            f"{req.comic_title} — Page {page_no}\n\n"
            f"**STYLE (MANDATORY FOR CONSISTENCY):**\n"
            f'The overall artistic style must be consistent with the **"{req.style}"** theme. '
            "This includes the environment, mood, and color palette. Use bold, clean line work with dynamic lighting.\n\n"
            f"**REFERENCE (HIGHEST PRIORITY):**\n"
            "Maintain visual continuity (character, pose, environment, and palette) with the previous page.\n\n"
            "**PAGE-SPECIFIC PANELS (ILLUSTRATE THE FOLLOWING):\n"
            + "\n".join(numbered)
        )

        log.info(f"prompt is {prompt}")

        # mark running before hitting the API
        mark_page_status(manifest_file, page_no, "running", {"ref": prev_ref, "prompt_chars": len(prompt)})

        path = generate_page(
            idx,
            prompt,
            output_filename_prefix=out_prefix,
            image_ref_path=prev_ref,        # <-- previous page becomes the reference
            manifest_file=manifest_file,    # <-- REQUIRED (fixes your error)
            model=None,
            size=None,
            retries=3,
            delay=2.0,
        )

        if path:
            results.append(path)
            prev_ref = path  # chain
            if on_page_done:
                try:
                    on_page_done(idx, path)
                except Exception as cb_e:
                    # don't crash the loop if callback fails
                    log.error(f"on_page_done failed for page {page_no}: {cb_e}")
        else:
            # stop on first failure; resume can continue later
            break

    return results


# Keep your original build_page_prompts if you still need it elsewhere.
# It will no longer be used by the chained renderer, which builds per-page prompts dynamically.

def render_pages_from_prompts(prompts: List[str], *, workdir: str, image_ref: str) -> List[str]:
    # Deprecated for continuity use-case; kept for compatibility.
    return generate_pages(
        prompts,
        output_prefix=f"{workdir}/page",
        image_ref_path=image_ref,
    )


def generate_pages(
    prompts: List[str],
    *,
    max_workers: int = 2,
    output_prefix: str = "page",
    model: Optional[str] = None,
    size: Optional[str] = None,
    image_ref_path: str,
    on_page_done: Optional[Callable[[int, str], None]] = None,
) -> List[str]:
    """
    Original parallel generator (kept for reuse). For continuity, prefer render_pages_chained().
    """
    results: List[Optional[str]] = [None] * len(prompts)
    model = model or config.openai_image_model
    size = size or config.image_size

    def _worker(i: int, p: str) -> Optional[str]:
        path = generate_page(
            i,
            p,
            output_filename_prefix=output_prefix,
            model=model,
            size=size,
            image_ref_path=image_ref_path,
        )
        if path and on_page_done:
            try:
                on_page_done(i, path)
            except Exception as e:
                log.error(f"on_page_done failed for page {i+1}: {e}")
        return path

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as ex:
        fut_map = {ex.submit(_worker, i, p): i for i, p in enumerate(prompts)}
        for fut in concurrent.futures.as_completed(fut_map):
            i = fut_map[fut]
            try:
                results[i] = fut.result()
            except Exception as e:
                log.exception(f"🔥 Unexpected error on page {i + 1}: {e}")
                results[i] = None

    return [f for f in results if f]


def generate_page(
    page_idx: int,
    prompt: str,
    *,
    output_filename_prefix: str,
    image_ref_path: str,
    manifest_file: str,
    gcs_prefix: Optional[str] = None,     # e.g., f"jobs/{job_id}"
    model: Optional[str] = None,
    size: Optional[str] = None,
    retries: int = 3,
    delay: float = 2.0,                   # base backoff seconds
) -> Optional[str]:
    """
    Generate a single page using images.edit with the provided reference image file.

    Returns:
      - local filename (str) on success
      - None on final failure (after retries)
    """
    model = model or config.openai_image_model
    size  = size  or config.image_size

    page_number   = page_idx + 1
    filename      = f"{output_filename_prefix}-{page_number}.png"
    tmpname       = f"{filename}.part"
    os.makedirs(os.path.dirname(filename) or ".", exist_ok=True)

    # Mark page as running (only once at the start)
    mark_page_status(manifest_file, page_number, "running", {
        "attempts": 0,
        "prompt_chars": len(prompt),
    })

    last_error = None

    for attempt in range(1, retries + 1):
        try:
            mark_page_status(manifest_file, page_number, "running", {"attempts": attempt})

            log.info(f"[page {page_number}] editing with ref={image_ref_path} (attempt {attempt}/{retries})")
            with open(image_ref_path, "rb") as ref_f:
                resp = client.images.edit(
                    model=model,
                    prompt=prompt,
                    size=size,
                    n=1,
                    image=ref_f,
                )

            b64 = resp.data[0].b64_json

            # --- Atomic save ---
            with open(tmpname, "wb") as f:
                f.write(base64.b64decode(b64))
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmpname, filename)

            log.info(f"[page {page_number}] ✅ saved to {filename}")

            # Mark as rendered locally BEFORE trying to upload
            mark_page_status(manifest_file, page_number, "rendered", {
                "attempts": attempt,
                "local": filename,
            })

            # Try GCS upload (optional)
            if gcs_prefix:
                try:
                    object_name = f"{gcs_prefix}/pages/page-{page_number}.png"
                    info = upload_to_gcs(filename, object_name=object_name)
                    mark_page_status(manifest_file, page_number, "done", {
                        "attempts": attempt,
                        "uploaded": True,
                        "gcs": info,
                        "local": filename,
                    })
                except Exception as up_e:
                    log.exception(f"[page {page_number}] GCS upload failed: {up_e}")
                    # Keep it as rendered so resume/status can see progress
                    mark_page_status(manifest_file, page_number, "rendered", {
                        "attempts": attempt,
                        "uploaded": False,
                        "upload_error": str(up_e),
                        "local": filename,
                    })

            return filename  # success path (even if upload failed, we keep the file)

        except Exception as e:
            last_error = str(e)
            log.warning(f"[page {page_number}] ⚠️ generate failed on attempt {attempt}/{retries}: {e}")

            # small exponential backoff with jitter before next attempt
            if attempt < retries:
                sleep_s = (delay * (2 ** (attempt - 1))) + random.uniform(0, 0.5)
                time.sleep(sleep_s)

    # Final failure:
    log.error(f"[page {page_number}] ❌ failed after {retries} attempts: {last_error}")
    mark_page_status(manifest_file, page_number, "failed", {
        "attempts": retries,
        "last_error": last_error,
    })
    # cleanup partial file if exists
    try:
        if os.path.exists(tmpname):
            os.remove(tmpname)
    except Exception:
        pass

    return None

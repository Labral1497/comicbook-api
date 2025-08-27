# app/features/comic/service.py
from __future__ import annotations

import base64
import os
from typing import List, Optional

from app.config import config
from app.features.full_script.schemas import Page, Panel
from app.logger import get_logger
from app.lib.openai_client import client
from app.lib.gcs_inventory import upload_to_gcs
from app.lib.jobs import load_manifest, mark_page_status
from app.features.pages.schemas import ComicRequest


log = get_logger(__name__)


def _numbered_panel_lines(panels: List[Panel]) -> List[str]:
    lines: List[str] = []
    for panel in panels:
        ln = f"{panel.panel_number}) Art: {panel.art_description.strip()}"
        if panel.dialogue.strip(): ln += f" | Dialogue: {panel.dialogue.strip()}"
        if panel.narration.strip(): ln += f" | Narration: {panel.narration.strip()}"
        if panel.sfx.strip(): ln += f" | SFX: {panel.sfx.strip()}"
        lines.append(ln)
    return lines


def _build_page_prompt(req: ComicRequest, page: Page) -> str:
    numbered = _numbered_panel_lines(page.panels)
    return (
        f"{req.comic_title} — Page {page.page_number}\n\n"
        f"**STYLE (MANDATORY FOR CONSISTENCY):**\n"
        f'The overall artistic style must be consistent with the **"{req.style}"** theme. '
        "This includes the environment, mood, and color palette. Use bold, clean line work with dynamic lighting.\n\n"
        f"**REFERENCE (HIGHEST PRIORITY):**\n"
        "The main character's face and unique features MUST closely match the previous page image (see attached).\n\n"
        "**CONTINUITY REQUIREMENTS (DO NOT BREAK):**\n"
        "Maintain visual continuity (character, pose, environment, and palette) with the previous page (see attached).\n\n"
        "**PAGE-SPECIFIC PANELS (ILLUSTRATE THE FOLLOWING):**\n"
        + "\n".join(numbered)
    )


def render_pages_chained(
    *,
    req: ComicRequest,
    workdir: str,
    cover_image_ref: str,
    manifest_file: str,
    gcs_prefix: Optional[str] = None,
) -> List[str]:
    """
    Sequential generation where page N uses page N-1 as a reference image.
    Page 1 uses the cover image as reference.
    """
    out_prefix = os.path.join(workdir, "page")
    results: List[str] = []
    prev_ref = cover_image_ref

    for idx, page in enumerate(req.pages):
        mf = load_manifest(manifest_file)
        if mf.get("cancelled"):
            log.info(f"[job cancelled] stopping at page {idx+1}")
            break
        page_no = idx + 1
        prompt = _build_page_prompt(req, page)

        # mark running
        mark_page_status(
            manifest_file,
            page_no,
            "running",
            {"prompt_chars": len(prompt), "ref": prev_ref},
        )

        filename = f"{out_prefix}-{page_no}.png"
        tmpname = f"{filename}.part"
        os.makedirs(os.path.dirname(filename) or ".", exist_ok=True)

        model = config.openai_image_model
        size = config.image_size
        retries = 3
        delay = 2.0
        last_error = None

        for attempt in range(1, retries + 1):
            try:
                mark_page_status(manifest_file, page_no, "running", {"attempts": attempt})
                with open(prev_ref, "rb") as ref_f:
                    resp = client.images.edit(
                        model=model,
                        prompt=prompt,
                        size=size,
                        n=1,
                        image=ref_f,
                    )
                b64 = resp.data[0].b64_json

                # atomic write
                with open(tmpname, "wb") as f:
                    f.write(base64.b64decode(b64))
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmpname, filename)

                mark_page_status(
                    manifest_file,
                    page_no,
                    "rendered",
                    {"attempts": attempt, "local": filename},
                )

                # try upload this page
                if gcs_prefix:
                    try:
                        object_name = f"{gcs_prefix}/pages/page-{page_no}.png"
                        info = upload_to_gcs(filename, object_name=object_name)
                        mark_page_status(
                            manifest_file,
                            page_no,
                            "done",
                            {"attempts": attempt, "uploaded": True, "gcs": info, "local": filename},
                        )
                    except Exception as up_e:
                        log.exception(f"GCS upload failed for page {page_no}: {up_e}")
                        mark_page_status(
                            manifest_file,
                            page_no,
                            "rendered",
                            {"attempts": attempt, "uploaded": False, "upload_error": str(up_e), "local": filename},
                        )

                # success — chain next page to this output
                results.append(filename)
                prev_ref = filename
                break

            except Exception as e:
                last_error = str(e)
                log.warning(f"[page {page_no}] generate failed attempt {attempt}/{retries}: {e}")
                if attempt < retries:
                    import random, time
                    time.sleep((delay * (2 ** (attempt - 1))) + random.uniform(0, 0.5))

        if not os.path.exists(filename):
            # final failure for this page; mark and stop the chain
            mark_page_status(manifest_file, page_no, "failed", {"last_error": last_error})
            break

    return results

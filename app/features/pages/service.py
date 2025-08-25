# app/features/comic/service.py
import base64
import os
import time
import concurrent.futures

from typing import List, Optional
from app.lib.openai_client import client
from app.config import config
from app.features.pages.schemas import ComicRequest
from app.logger import get_logger

log = get_logger(__name__)

def build_page_prompts(req: ComicRequest) -> List[str]:
    """
    Mirrors your original logic:
    - If ref_path exists, add REFERENCE line with uploaded file path
    - Else if req.image_ref exists, add REFERENCE line with URL/path
    - Always format '4 panels:' then enumerate provided panel strings
    """
    prompts: List[str] = []
    for page in req.pages:
        page_num = page.page_number
        numbered: List[str] = []
        for panel in page.panels:
            pn          = panel.panel_number
            art         = panel.art_description.strip()
            dialogue    = panel.dialogue.strip()
            narration   = panel.narration.strip()
            sfx         = panel.sfx.strip()

            line = f"{pn}) Art: {art}"
            if dialogue:
                line += f" | Dialogue: {dialogue}"
            if narration:
                line += f" | Narration: {narration}"
            if sfx:
                line += f" | SFX: {sfx}"
            numbered.append(line)

        prompt = (
            f"{req.comic_title} — Page {page_num}\n\n"
            f"**STYLE (MANDATORY FOR CONSISTENCY):**\n"
            f'The overall artistic style must be consistent with the **"{req.style}"** theme. '
            "This includes the environment, mood, and color palette. Use bold, clean line work with dynamic lighting.\n\n"
            f"**REFERENCE (HIGHEST PRIORITY):**\n"
            "The main character's face and unique features MUST closely match the person in the uploaded **cover image** (see attached). "
            "This is the most important rule.\n\n"
            "**PAGE-SPECIFIC PANELS (ILLUSTRATE THE FOLLOWING):\n"
            + "\n".join(numbered)
        )
        prompts.append(prompt)
    return prompts

def render_pages_from_prompts(prompts: List[str], *, workdir: str, image_ref: str) -> List[str]:
    return generate_pages(
        prompts,
        output_prefix=f"{workdir}/page",
        image_ref_path=image_ref,
        # model/size/max_workers pulled from config inside generate_pages
    )

def generate_pages(
    prompts: List[str],
    *,
    max_workers: int = 2,
    output_prefix: str = "page",
    model: Optional[str] = None,
    size: Optional[str] = None,
    image_ref_path: str,
) -> List[str]:
    results: List[Optional[str]] = [None] * len(prompts)
    model = model or config.openai_image_model
    size = size or config.image_size

    def _worker(i: int, p: str) -> Optional[str]:
        return generate_page(
            i,
            p,
            output_filename_prefix=output_prefix,
            model=model,
            size=size,
            image_ref_path=image_ref_path,
        )

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as ex:
        fut_map = {ex.submit(_worker, i, p): i for i, p in enumerate(prompts)}
        for fut in concurrent.futures.as_completed(fut_map):
            i = fut_map[fut]
            try:
                results[i] = fut.result()
            except Exception as e:
                print(f"🔥 Unexpected error on page {i + 1}: {e}")
                results[i] = None

    return [f for f in results if f]

def generate_page(
    page_idx: int,
    prompt: str,
    *,
    output_filename_prefix: str,
    model: Optional[str] = None,
    size: Optional[str] = None,
    retries: int = 3,
    delay: float = 5.0,
    image_ref_path: str,
) -> Optional[str]:
    model = model or config.openai_image_model
    size = size or config.image_size
    for attempt in range(1, retries + 1):
        try:
            log.info(f"prompt is {prompt}")
            resp = client.images.edit(
                model="gpt-image-1",
                prompt=prompt,
                size=size,
                n=1,
                image=open(image_ref_path, "rb"),
            )
            b64 = resp.data[0].b64_json
            log.info(f"Generating page {page_idx + 1} with prompt length {len(prompt)} chars")
            filename = f"{output_filename_prefix}-{page_idx + 1}.png"
            os.makedirs(os.path.dirname(filename) or ".", exist_ok=True)
            with open(filename, "wb") as f:
                f.write(base64.b64decode(b64))
            print(f"✅ Saved {filename}")
            return filename
        except Exception as e:
            print(f"⚠️ Error generating page {page_idx + 1} (attempt {attempt}/{retries}): {e}")
            if attempt < retries:
                time.sleep(delay)
    print(f"❌ Failed to generate page {page_idx + 1} after {retries} retries")
    return None

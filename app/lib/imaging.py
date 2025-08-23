# app/lib/imaging.py
import base64
import concurrent.futures
import time
import os
from typing import List, Optional
from app.config import config
from app import logger
from app.lib.openai_client import client as _client

log = logger.get_logger(__name__)

def generate_page(
    page_idx: int,
    prompt: str,
    *,
    output_filename_prefix: str,
    model: Optional[str] = None,
    size: Optional[str] = None,
    retries: int = 3,
    delay: float = 5.0,
) -> Optional[str]:
    model = model or config.openai_image_model
    size = size or config.image_size
    for attempt in range(1, retries + 1):
        try:
            log.info(f"prompt is {prompt}")
            resp = _client.images.generate(
                model="gpt-image-1",
                prompt=prompt,
                size=size,
                n=1,
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


def generate_pages(
    prompts: List[str],
    *,
    max_workers: int = 1,
    output_prefix: str = "page",
    model: Optional[str] = None,
    size: Optional[str] = None,
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

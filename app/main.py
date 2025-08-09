# main.py
import time
import base64
import concurrent.futures
from typing import List, Optional

from openai import OpenAI
from PIL import Image
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from app import logger, config

log = logger.get_logger(__name__)
_client = OpenAI(api_key=config.openai_api_key)

# ------------------------
# IMAGE GENERATION (single)
# ------------------------
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
    """
    Generate one image for a page using a fully-formed prompt string.
    Returns the saved filename, or None on failure.
    """
    model = model or config.openai_image_model
    size = size or config.image_size
    for attempt in range(1, retries + 1):
        try:
            resp = _client.images.generate(
                model="gpt-image-1",
                prompt=prompt,
                size=size,
                n=1,
            )
            b64 = resp.data[0].b64_json
            log.info(f"Generating page {page_idx + 1} with prompt length {len(prompt)} chars")
            filename = f"{output_filename_prefix}-{page_idx + 1}.png"
            log.info(f"Saving page {page_idx + 1} to: {filename}")
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


# ------------------------
# IMAGE GENERATION (batch)
# ------------------------
def generate_pages(
    prompts: List[str],
    *,
    max_workers: int = 1,
    output_prefix: str = "page",
    model: Optional[str] = None,
    size: Optional[str] = None,
) -> List[str]:
    """
    Generate many images in parallel from a list of fully-formed prompts.
    Returns a list of successfully created filenames in original order (failed pages omitted).
    """
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

    # compact out failures, preserving order
    return [f for f in results if f]


# ------------------------
# PDF COMPOSITION
# ------------------------
def make_pdf(files: List[str], pdf_name: str = "comic.pdf") -> str:
    """
    Combine images into a single A4 PDF—one image per page, centered and scaled.
    """
    log.info(f"Combining {len(files)} pages into PDF: {pdf_name}")
    c = canvas.Canvas(pdf_name, pagesize=A4)
    w, h = A4
    for file in files:
        img = Image.open(file)
        img_ratio = img.width / img.height
        if w / h > img_ratio:
            ih = h
            iw = ih * img_ratio
        else:
            iw = w
            ih = iw / img_ratio
        x = (w - iw) / 2
        y = (h - ih) / 2
        c.drawImage(file, x, y, iw, ih)
        c.showPage()
    c.save()
    print(f"📄 Comic saved as {pdf_name}")
    return pdf_name


# ------------------------
# CLI self-test (does nothing on import by FastAPI)
# ------------------------
if __name__ == "__main__":
    demo_prompts = [
        "Demo Comic — Page 1: Test\nSTYLE: Minimal\nCHARACTER: Test\n4 panels:\n1) A\n2) B\n3) C\n4) D"
    ]
    out = generate_pages(demo_prompts, output_prefix="demo-page")
    if out:
        make_pdf(out, pdf_name="demo.pdf")

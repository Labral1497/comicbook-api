# main.py
import base64
import concurrent.futures
import json
import os
import time
from typing import List, Optional


from openai import OpenAI
from PIL import Image
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from app.config import config
from app import logger
from app.schemas import StoryIdeasRequest, StoryIdeasResponse, StoryIdea

log = logger.get_logger(__name__)
_client = OpenAI(api_key=config.openai_api_key)
_text_client = OpenAI(api_key=config.openai_api_key)

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


async def story_ideas(req: StoryIdeasRequest) -> StoryIdeasResponse:
    """
    Generate 3 funny story ideas (title + one-sentence synopsis) using the OpenAI chat API.
    """
    user_prompt = f"""
        I will add answers to some questions
        I want you to generate 3 hilarious stories ideas include 2 things- title and synopsis ( 1- generate a synopsis- one funny explanatory sentence catchy used for marketing to summarize the book's appeal, 2-  funny comic book name) for a funny comic book based on the questions

        Here are the questions and the answers-

        Whats the name of the main character? {req.name}
        Theme of the comic? {req.theme}
        What the character do for his work? {req.job}
        Whats his dream? {req.dream}
        Where is Yaron from? {req.origin}
        What his funny hobby? {req.hobby}
        What is something the character is saying often? "{req.catchphrase}"
        What does he know better than anyone? {req.super_skill}
        Whats his favorite place? {req.favorite_place}
        What his taste in woman? {req.taste_in_women}
        """.strip()

    system = (
        "You are a witty copywriter. Generate EXACTLY three ideas. "
        "Return STRICT JSON only, with shape: "
        '{"ideas":[{"title":"string","synopsis":"string"},{"title":"string","synopsis":"string"},{"title":"string","synopsis":"string"}]} '
        "No extra text, no comments, no markdown. Each synopsis must be ONE punchy marketing sentence."
    )

    try:
        resp = _text_client.chat.completions.create(
            model=os.getenv("OPENAI_TEXT_MODEL", getattr(config, "openai_text_model", "gpt-4o-mini")),
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.9,
        )
        raw = (resp.choices[0].message.content or "").strip()

        # Strip code fences if present
        cleaned = raw
        if cleaned.startswith("```"):
            cleaned = cleaned.strip("`")
            if cleaned.lower().startswith("json"):
                cleaned = cleaned[4:].lstrip()

        data = json.loads(cleaned)
        ideas = [StoryIdea(**i) for i in data.get("ideas", [])][:3]
        if len(ideas) != 3:
            raise ValueError("Model did not return exactly 3 ideas")
        return StoryIdeasResponse(ideas=ideas)

    except Exception as e:
        log.error(f"/story-ideas parse error: {e}")
        return StoryIdeasResponse(ideas=[])

def generate_comic_cover(
    cover_art_description: str,
    user_theme: str,
    *,
    output_path: str,
    image_ref_path: Optional[str] = None,
    model: Optional[str] = None,
    size: Optional[str] = None,
) -> str:
    """
    Generate a single comic cover image and save to output_path.
    Returns output_path.
    """
    model = model or config.openai_image_model
    # Cover wants “4K” in spirit; actual allowed sizes are limited—use config or "auto"
    size = size or config.image_size  # valid: 1024x1024 | 1024x1536 | 1536x1024 | auto

    ref_block = ""
    if image_ref_path:
        ref_block = (
            f"\n**REFERENCE PHOTO (MANDATORY):** The main character must closely resemble "
            f"the person in this image file path: {image_ref_path}. Focus on hairstyle, hair color/patterns, "
            f"eyebrow shape, eye area (don’t invent eye color if obscured), facial hair style, skin tone, and "
            f"visible head/face accessories (glasses, hats, piercings, earrings)."
        )

    prompt = f"""
Create a vibrant, ultra-high-resolution comic book cover. The artwork should be a masterpiece of digital illustration, suitable for a professional digital print.

**PRIMARY SUBJECT & SCENE (MANDATORY):**
* **Main Character Resemblance:** The central figure must be illustrated to closely resemble the person in the provided image. **Focus specifically on these unique facial features, hair, and head/face accessories:** hairstyle, hair color and patterns, eyebrow shape, eye area (without guessing eye color if hidden), facial hair style (if any), skin tone, and any notable accessories such as glasses, hats, piercings, or earrings visible in the image.
* **Scene Description:** The illustration must bring this scene to life: **"{cover_art_description}"**. Capture the action, expression, and mood described in the scene, ensuring the main character is central to this scene and rendered with the specified resemblance.
{ref_block}

**ARTISTIC STYLE & EXECUTION (MANDATORY):**
* **Core Style:** Professional digital comic book art. Bold, clean line work with dynamic, cinematic lighting and shadows.
* **Theme Influence:** The visual style should be heavily influenced by the **"{user_theme}"** theme.
* **Color Palette:** Use a vibrant, saturated, and eye-catching color palette that makes the cover pop. Unless the theme requires otherwise.
* **Quality:** Render with hyper-detailed, sharp focus, epic quality (cover-grade).

**COMMERCIAL DETAILS (MANDATORY):**
* To make this look like an authentic comic book you would find in a store, you MUST include the following elements:
  1. **Barcode:** Place a realistic-looking UPC barcode in the bottom corner (e.g., bottom-left).
  2. **Humorous Sticker/Burst:** Add a fun, flashy sticker or starburst shape somewhere on the cover with a funny emblem (no real text).

**CRITICAL RULE:**
* **No real-world brands or text.** All branding and text on the commercial details (barcode, sticker, etc.) must be completely fictional. Use gibberish or non-sensical symbols instead of legible characters to avoid any trademark issues.
""".strip()

    log.info("Generating comic cover...")
    resp = _client.images.generate(model=model, prompt=prompt, size=size, n=1)
    b64 = resp.data[0].b64_json

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "wb") as f:
        f.write(base64.b64decode(b64))

    log.info(f"✅ Cover saved to {output_path}")
    return output_path

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

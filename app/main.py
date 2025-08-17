# main.py
import base64
import concurrent.futures
import json
import os
import time
from typing import List, Optional
from pydantic import ValidationError

from openai import OpenAI
from PIL import Image
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from app.config import config
from app import logger
from app.schemas import (
    StoryIdeasRequest,
    StoryIdeasResponse,
    StoryIdea,
    FullScriptRequest,
    FullScriptResponse,
)

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
        I will add answers to some questions.
        Generate 3 hilarious story ideas, each with FOUR fields:
        - title (funny comic book name)
        - synopsis (ONE witty marketing sentence summarizing the appeal)
        - character_description (compact, comma-separated attribute fragments, NOT a sentence)
        - cover_art_description (1–3 sentences describing a dynamic movie-poster-style cover)

        Rules for character_description:
        - Format: compact, comma-separated attribute fragments (no full sentences).
        - 4–8 fragments total, 1–4 words each. Examples:
        good → "30s, techwear hoodie, expressive eyebrows, short dark hair"
        good → "late 20s, lab coat, anxious energy, messy curls"
        bad  → "A superhero who loves dancing in the rain..." (sentence ❌)
        - No verbs, no proper names, no punctuation except commas.
        - Lowercase, no trailing period. May include numerals like "30s", "6’2”".

        Rules for cover_art_description:
        - 1–3 sentences; vivid and specific; think “movie poster.”
        - Mention camera angle/composition, the hero’s pose/expression, background/setting, lighting/mood, color palette, and any iconic prop/effect.
        - Do NOT include text elements (titles/SFX/logos) in the description itself.
        - No trademarks, no existing IP, no brand names.

        Output ONLY the JSON. No markdown, no commentary.

        Here are the questions and the answers—

        Whats the name of the main character? {req.name}
        Theme of the comic? {req.theme}
        What the character do for his work? {req.job}
        Whats his dream? {req.dream}
        Where is {req.name} from? {req.origin}
        What his funny hobby? {req.hobby}
        What is something the character is saying often? "{req.catchphrase}"
        What does he know better than anyone? {req.super_skill}
        Whats his favorite place? {req.favorite_place}
        What his taste in woman? {req.taste_in_women}
        """.strip()

    system = (
        "You are a witty copywriter. Generate EXACTLY three ideas. "
        "Return STRICT JSON only, with shape: "
        '{"ideas":[{"title":"string","synopsis":"string", "character_description": "string"},{"title":"string","synopsis":"string"},{"title":"string","synopsis":"string"}]} '
        "No extra text, no comments, no markdown. Each synopsis must be ONE punchy marketing sentence."
    )

    try:
        log.debug(f"user prompt: {user_prompt}")
        resp = _text_client.chat.completions.create(
            model=config.openai_text_model,
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
        log.debug(f"ideas response: {ideas}")
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
    log.debug(f"prompt is: {prompt}")
    resp = _client.images.generate(model=model, prompt=prompt, size=size, n=1)
    b64 = resp.data[0].b64_json

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "wb") as f:
        f.write(base64.b64decode(b64))

    log.debug(f"✅ Cover saved to {output_path}")
    return output_path

def build_full_script_prompt(req: FullScriptRequest) -> str:
    traits = ", ".join(req.user_answers_list) if req.user_answers_list else ""
    return f"""
You are an elite-level comic book writer and storyboard artist, a creative fusion of a master storyteller known for wit and charm, and a film director known for brilliant visual comedy. Your task is to write a complete, hilarious, and visually rich comic book script from start to finish, formatted as a single, clean JSON object.

CONTEXT & INPUTS:
* Story Synopsis to Adapt: "{req.chosen_story_idea}"
* Main Character Name: "{req.user_name}"
* Main Character Gender: "{req.user_gender}"
* Definitive Character Description (for illustration consistency): "{req.character_description}"
* Total Page Count: "{req.page_count}"
* Core Theme: "{req.user_theme}"
* Character's Comedic Traits (Source material for jokes, use them creatively): "{traits}"
* Panels per page must be between {req.min_panels_per_page} and {req.max_panels_per_page} (inclusive).
🔹 * For EACH page, CHOOSE a panel count **randomly within that range**, and **vary** counts across pages; do **not** use the same number on every page unless it serves a clear comedic or narrative purpose.

PRIMARY DIRECTIVE:
Generate a complete comic book script that adapts the provided synopsis into a brilliant and funny narrative. The script must be returned as a single JSON object, adhering strictly to the schema and mandates below. Use exactly {req.page_count} pages. Number panels 1..N on each page.

JSON SCHEMA (Your entire output MUST be a single JSON object that follows this exact structure):
{{
  "title": "A Catchy and Funny Title for the Comic",
  "tagline": "A Hilarious Subtitle or Punchy Quote",
  "cover_art_description": "A highly detailed description of a dynamic and exciting cover image. Describe the character's pose, expression, the background, the mood, and the central action. This should be like a 'movie poster' for the story.",
  "pages": [
    {{
      "page_number": 1,
      "panels": [
        {{
          "panel_number": 1,
          "art_description": "EXTREMELY detailed visual description. Describe camera angle (e.g., 'Wide shot', 'Close-up on face'), character's action, specific expression, background elements, and lighting. Be the eyes for the illustrator AI.",
          "dialogue": "Character Name: 'The dialogue for this panel.' or '' if there is no dialogue.",
          "narration": "A narration box text, like a storyteller's voice. or '' if there is none.",
          "sfx": "Sound effects like 'CRASH!', 'BEEP!', or 'THWUMP!'. Leave as '' if there are none."
        }}
      ]
    }}
  ]
}}

Output ONLY the JSON object. Do not wrap in markdown fences. Do not add commentary.
""".strip()

def _full_script_json_schema() -> dict:
    # JSON Schema that matches FullScriptResponse exactly
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "title": {"type": "string"},
            "tagline": {"type": "string"},
            "cover_art_description": {"type": "string"},
            "pages": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "page_number": {"type": "integer"},
                        "panels": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "additionalProperties": False,
                                "properties": {
                                    "panel_number": {"type": "integer"},
                                    "art_description": {"type": "string"},
                                    "dialogue": {"type": "string"},
                                    "narration": {"type": "string"},
                                    "sfx": {"type": "string"}
                                },
                                "required": [
                                    "panel_number",
                                    "art_description",
                                    "dialogue",
                                    "narration",
                                    "sfx"
                                ]
                            }
                        }
                    },
                    "required": ["page_number", "panels"]
                }
            }
        },
        "required": ["title", "tagline", "cover_art_description", "pages"]
    }

async def call_llm_return_json_string(prompt: str) -> str:
    """
    Calls GPT and returns the *raw JSON string* for FullScriptResponse.
    Uses Structured Outputs with a JSON Schema to guarantee shape.
    """
    # system primer keeps the model terse and JSON-only
    system_msg = (
        "You are an elite-level comic writer & storyboard artist. "
        "Return ONLY a single JSON object that strictly conforms to the provided JSON Schema. "
        "Do not add commentary or markdown fences."
    )

    resp = _text_client.chat.completions.create(
        model=config.openai_text_model,
        temperature=0.2,
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "FullScriptResponse",
                "schema": _full_script_json_schema(),
            },
        },
        messages=[
            {"role": "system", "content": system_msg},
            {"role": "user", "content": prompt},
        ],
    )

    content = resp.choices[0].message.content or ""
    return content.strip()

def _extract_json_str(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("{") and raw.endswith("}"):
        return raw
    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end != -1 and end > start:
        return raw[start:end+1]
    return raw  # let validation fail later

async def generate_full_script(req: FullScriptRequest) -> FullScriptResponse:
    prompt = build_full_script_prompt(req)
    raw = await call_llm_return_json_string(prompt)
    cleaned = _extract_json_str(raw)
    try:
        # pydantic v2
        return FullScriptResponse.model_validate_json(cleaned)
    except AttributeError:
        # pydantic v1 fallback
        from pydantic import parse_raw_as
        return parse_raw_as(FullScriptResponse, cleaned)
    except ValidationError as ve:
        raise ve


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

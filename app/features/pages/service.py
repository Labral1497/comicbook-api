# app/features/comic/service.py
from typing import List, Optional
from app.features.pages.schemas import ComicRequest
from app.lib.imaging import generate_pages

def build_page_prompts(req: ComicRequest, ref_path: Optional[str]) -> List[str]:
    """
    Mirrors your original logic:
    - If ref_path exists, add REFERENCE line with uploaded file path
    - Else if req.image_ref exists, add REFERENCE line with URL/path
    - Always format '4 panels:' then enumerate provided panel strings
    """
    prompts: List[str] = []
    for page in req.pages:
        character_block = req.character
        if ref_path:
            character_block = f"""{req.character}
REFERENCE: Match main character’s face to the uploaded image at {ref_path}"""
        elif req.image_ref:
            character_block = f"""{req.character}
REFERENCE: Match main character’s face to: {req.image_ref}"""

        numbered = [f"{i+1}) {txt}" for i, txt in enumerate(page.panels)]
        prompt = (
            f"{req.comic_title} — Page {page.id}: {page.title}\n"
            f"STYLE: {req.style}\n"
            f"CHARACTER: {character_block}\n"
            "4 panels:\n" + "\n".join(numbered)
        )
        prompts.append(prompt)
    return prompts

def render_pages_from_prompts(prompts: List[str], *, workdir: str) -> List[str]:
    return generate_pages(
        prompts,
        output_prefix=f"{workdir}/page",
        # model/size/max_workers pulled from config inside generate_pages
    )

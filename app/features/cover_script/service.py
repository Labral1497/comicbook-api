# app/features/cover_script/service.py
import json
from pydantic import ValidationError
from app.lib.openai_client import client
from .schemas import CoverScriptRequest, CoverScriptResponse
from .prompt import build_cover_script_prompt

SYSTEM = (
    "You are a witty, concise comic writer and storyboard artist. "
    "Return STRICT JSON only — exactly one JSON object with the keys "
    "'title', 'tagline', 'cover_art_description', and 'story_summary' (all strings). "
    "No extra text, no comments, no markdown."
)

async def generate_cover_script(req: CoverScriptRequest) -> CoverScriptResponse:
    traits = ", ".join(f"{q} - {a}" for q, a in req.user_answers_list.items()) if req.user_answers_list else ""
    prompt = build_cover_script_prompt(
        title=req.title, synopsis=req.synopsis, name=req.name,
        gender=req.gender, page_count=req.page_count, theme=req.theme, traits=traits
    )
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        temperature=0.7,
        messages=[
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": prompt},
        ],
    )
    raw = (resp.choices[0].message.content or "").strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"Model did not return valid JSON: {e}\nRaw: {raw}") from e

    try:
        return CoverScriptResponse(**data)
    except ValidationError as e:
        raise ValueError(f"Model JSON failed validation: {e}\nData: {data}") from e

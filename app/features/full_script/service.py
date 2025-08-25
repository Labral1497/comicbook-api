# app/features/full_script/service.py
from pydantic import ValidationError
import json
from app.lib.openai_client import client
from app.config import config
from .schemas import FullScriptRequest, FullScriptPagesResponse
from .prompt import build_full_script_prompt

def _full_script_json_schema() -> dict:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "pages": {
                "type": "array",
                "minItems": 1,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "page_number": {"type": "integer"},
                        "panels": {
                            "type": "array",
                            "minItems": 1,
                            "items": {
                                "type": "object",
                                "additionalProperties": False,
                                "properties": {
                                    "panel_number": {"type": "integer"},
                                    "art_description": {"type": "string"},
                                    "dialogue": {"type": "string"},
                                    "narration": {"type": "string"},
                                    "sfx": {"type": "string"},
                                },
                                "required": [
                                    "panel_number",
                                    "art_description",
                                    "dialogue",
                                    "narration",
                                    "sfx",
                                ],
                            },
                        },
                    },
                    "required": ["page_number", "panels"],
                },
            }
        },
        "required": ["pages"],
    }

async def call_llm_return_json_string(prompt: str) -> str:
    system_msg = (
        "You are an elite-level comic writer & storyboard artist. "
        "Return ONLY a single JSON object that strictly conforms to the provided JSON Schema. "
        "Do not add commentary or markdown fences."
    )
    resp = client.chat.completions.create(
        model=config.openai_text_model,
        temperature=0.2,
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "FullScriptPagesResponse",
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
    return raw

async def generate_full_script(req: FullScriptRequest) -> FullScriptPagesResponse:
    prompt = build_full_script_prompt(req)
    raw = await call_llm_return_json_string(prompt)
    cleaned = _extract_json_str(raw)
    try:
        # pydantic v2
        return FullScriptPagesResponse.model_validate_json(cleaned)
    except AttributeError:
        from pydantic import parse_raw_as
        return parse_raw_as(FullScriptPagesResponse, cleaned)
    except ValidationError as ve:
        raise ve

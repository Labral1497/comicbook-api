# app/features/full_script/service.py
from pydantic import ValidationError
import json
from app.lib.openai_client import client
from app.config import config
from .schemas import FullScriptRequest, FullScriptPagesResponse
from .prompt import build_full_script_prompt

def _full_script_json_schema() -> dict:
    # ---- reusable pieces ----
    string = {"type": "string"}
    str_array = {"type": "array", "items": string}

    # Panel schema (with optional ids)
    panel_schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "panel_number": {"type": "integer"},
            "art_description": string,
            "dialogue": string,
            "narration": string,
            "sfx": string,
            # NEW optional fields:
            "characters": str_array,
            "props": str_array,
            "location_id": string,
        },
        "required": ["panel_number", "art_description", "dialogue", "narration", "sfx"],
    }

    # Page schema (with optional ids)
    page_schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "page_number": {"type": "integer"},
            "panels": {
                "type": "array",
                "minItems": 1,
                "items": panel_schema,
            },
            # NEW optional fields:
            "location_id": string,
            "characters": str_array,
            "props": str_array,
        },
        "required": ["page_number", "panels"],
    }

    # Lookbook delta stubs
    character_to_add = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "id": string,
            "display_name": string,
            "role": string,
            "visual_stub": string,
            "needs_concept_sheet": {"type": "boolean"},
        },
        "required": ["id", "display_name", "needs_concept_sheet"],
    }
    location_to_add = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "id": string,
            "name": string,
            "visual_stub": string,
            "needs_concept_sheet": {"type": "boolean"},
        },
        "required": ["id", "name", "needs_concept_sheet"],
    }
    prop_to_add = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "id": string,
            "name": string,
            "visual_stub": string,
            "needs_concept_sheet": {"type": "boolean"},
        },
        "required": ["id", "name", "needs_concept_sheet"],
    }

    lookbook_delta_schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "characters_to_add": {"type": "array", "items": character_to_add},
            "locations_to_add": {"type": "array", "items": location_to_add},
            "props_to_add": {"type": "array", "items": prop_to_add},
        },
        "required": [],
    }

    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "pages": {
                "type": "array",
                "minItems": 1,
                "items": page_schema,
            },
            # NEW: let the writer declare new entities
            "lookbook_delta": lookbook_delta_schema,
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

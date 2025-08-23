# app/lib/json_tools.py
import json
import re

def extract_json_block(text: str) -> str:
    s = text.strip()
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?\s*", "", s, flags=re.IGNORECASE)
        s = re.sub(r"\s*```$", "", s)
    try:
        json.loads(s)
        return s
    except Exception:
        pass
    m = re.search(r"\[.*\]", s, flags=re.DOTALL)
    if m:
        return m.group(0)
    m = re.search(r"\{.*\}", s, flags=re.DOTALL)
    return m.group(0) if m else s

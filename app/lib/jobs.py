# app/lib/jobs.py
import json, os
from typing import Dict, List, Any

def manifest_path(workdir: str) -> str:
    return os.path.join(workdir, "manifest.json")

def load_manifest(path: str) -> Dict[str, Any]:
    if not os.path.exists(path):
        return {"pages": {}, "final": None}
    with open(path, "r") as f:
        return json.load(f)

def save_manifest(path: str, data: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)

def pages_done(manifest: Dict[str, Any]) -> List[int]:
    return sorted([int(k) for k, v in manifest["pages"].items() if v.get("status") == "done"])

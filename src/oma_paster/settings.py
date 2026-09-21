"""User settings (models, device, appearance) persisted next to the rest of the local data."""

from __future__ import annotations

import json
from typing import Any

from oma_paster import store

PATH = store.DATA / "settings.json"

DEFAULTS: dict[str, Any] = {
    "extractor_model": "fastino/gliner2.5-small-v1",
    "matcher_model": "sentence-transformers/all-MiniLM-L6-v2",
    "device": "cpu",
    "appearance": {"font_size": 14, "font": "mono"},
}

# Known-good choices offered in the UI (custom Hugging Face ids are allowed too).
OPTIONS = {
    "extractor": [
        {"id": "fastino/gliner2.5-small-v1", "label": "GLiNER 2.5 small", "note": "default · fastest"},
        {"id": "fastino/gliner2.5-base-v1", "label": "GLiNER 2.5 base", "note": "larger, slower, usually more accurate"},
        {"id": "fastino/gliner2.5-multi-v1", "label": "GLiNER 2.5 multilingual", "note": "resumes in other languages"},
        {"id": "fastino/gliner2-large-v1", "label": "GLiNER 2 large", "note": "biggest, slowest"},
    ],
    "matcher": [
        {"id": "sentence-transformers/all-MiniLM-L6-v2", "label": "MiniLM L6", "note": "default · tiny, English"},
        {"id": "BAAI/bge-small-en-v1.5", "label": "BGE small", "note": "slightly larger, English"},
        {"id": "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2", "label": "MiniLM multilingual", "note": "forms in other languages"},
    ],
}


def load() -> dict[str, Any]:
    try:
        saved = json.loads(PATH.read_text())
    except (OSError, ValueError):
        saved = {}
    out = {**DEFAULTS, **{k: v for k, v in saved.items() if k in DEFAULTS and k != "appearance"}}
    appearance = saved.get("appearance") or {}
    out["appearance"] = {**DEFAULTS["appearance"], **{k: v for k, v in appearance.items() if k in DEFAULTS["appearance"]}}
    return out


def update(patch: dict[str, Any]) -> dict[str, Any]:
    cur = load()
    for k, v in patch.items():
        if k == "appearance" and isinstance(v, dict):
            cur["appearance"].update({a: b for a, b in v.items() if a in DEFAULTS["appearance"]})
        elif k in DEFAULTS and k != "appearance" and isinstance(v, str) and v.strip():
            cur[k] = v.strip()
    store._write_private(PATH, json.dumps(cur, indent=2).encode())
    return cur

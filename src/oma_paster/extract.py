"""Resume / clipboard → labeled entities via GLiNER2.5-small (+ light regex helpers)."""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass

from cua_s1.pdf import derive_entities
from cua_s1.schema import Entity

# Schema labels for GLiNER — descriptions help zero-shot quality.
GLINER_LABELS: dict[str, str] = {
    "person_name": "Full name of the person the resume belongs to",
    "email": "Email address",
    "phone": "Phone or mobile number",
    "job_title": "Current or most recent job title / position",
    "company": "Current or most recent employer / company",
    "location": "City, region, or location",
    "x_handle": "X (Twitter) username or profile URL",
    "github": "GitHub username or profile URL",
    "website": "Personal website or portfolio URL",
    "date_of_birth": "Date of birth if present",
}

# Document labels aligned to cua-s1's synthetic concept catalogue.
LABEL_MAP: dict[str, str] = {
    "person_name": "Name",
    "email": "Email",
    "phone": "Phone",
    "job_title": "Title",
    "company": "Employer",
    "location": "City",
    "x_handle": "X",
    "github": "GitHub",
    "website": "Website",
    "date_of_birth": "Date of birth",
}

EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
PHONE_RE = re.compile(
    r"(?:\+?\d{1,3}[\s.-]?)?(?:\(?\d{3}\)?[\s.-]?)\d{3}[\s.-]?\d{4}\b"
)
DOB_RE = re.compile(r"^\s*(\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}|\d{4}-\d{2}-\d{2}|[A-Za-z]{3,9}\.? \d{1,2},? \d{4}|\d{1,2} [A-Za-z]{3,9}\.? \d{4})\s*$")
LINKEDIN_RE = re.compile(r"(?:https?://)?(?:[a-z]{2,3}\.)?linkedin\.com/in/([A-Za-z0-9_%-]{2,100})", re.I)
X_URL_RE = re.compile(
    r"(?:https?://)?(?:www\.)?(?:x\.com|twitter\.com)/([A-Za-z0-9_]{1,15})\b",
    re.I,
)
GITHUB_URL_RE = re.compile(
    r"(?:https?://)?(?:www\.)?github\.com/([A-Za-z0-9-]{1,39})\b",
    re.I,
)
HANDLE_RE = re.compile(r"(?i)\b(?:x|twitter)\s*[:@]\s*@?([A-Za-z0-9_]{1,15})\b")
GITHUB_HANDLE_RE = re.compile(r"(?i)\bgithub\s*[:/@]\s*@?([A-Za-z0-9-]{1,39})\b")
LINE_KV = re.compile(
    r"^\s*([A-Za-z][A-Za-z0-9 .'/#&()-]{1,40}?)\s*[:\u2013-]\s+(.+?)\s*$"
)


@dataclass
class ExtractionResult:
    entities: list[Entity]
    source: str
    timings_ms: dict[str, float]


class Extractor:
    """Lazy-loads GLiNER once; thread-safe for the demo server."""

    def __init__(self, model_id: str = "fastino/gliner2.5-small-v1", device: str = "cpu") -> None:
        self.model_id = model_id
        self.device = device
        self._model = None
        self._lock = threading.Lock()

    def ensure_loaded(self) -> None:
        with self._lock:
            if self._model is not None:
                return
            from gliner2 import AutoExtractor

            self._model = AutoExtractor.from_pretrained(
                self.model_id,
                map_location=self.device,
            )

    def extract(self, text: str) -> ExtractionResult:
        import time

        cleaned = text.strip()
        if not cleaned:
            return ExtractionResult(entities=[], source="empty", timings_ms={})

        started = time.perf_counter()
        self.ensure_loaded()
        loaded_at = time.perf_counter()

        by_key: dict[str, str] = {}
        _merge_regex(cleaned, by_key)
        _merge_line_kv(cleaned, by_key)

        assert self._model is not None
        result = self._model.extract_entities(
            cleaned,
            GLINER_LABELS,
            include_confidence=True,
        )
        inferred_at = time.perf_counter()

        entities_block = result.get("entities", {}) if isinstance(result, dict) else {}
        for key, spans in entities_block.items():
            if key in by_key or not spans:
                continue
            best = max(spans, key=lambda item: float(item.get("confidence") or 0.0))
            if key == "location":
                # The header holds the current location; later ones are past jobs.
                head = [x for x in spans if 0 <= cleaned.find(str(x.get("text") or "")) < 400]
                if head:
                    best = min(head, key=lambda x: cleaned.find(str(x.get("text") or "")))
            value = str(best.get("text") or "").strip()
            if key == "date_of_birth" and not DOB_RE.search(value):
                continue  # e.g. a job's "Jan 2021 – Aug 2022" range is not a birth date
            if value:
                by_key[key] = _normalize_value(key, value)

        entities = [
            Entity(LABEL_MAP[key], value)
            for key, value in by_key.items()
            if key in LABEL_MAP and value
        ]
        linkedin = LINKEDIN_RE.search(cleaned)
        if linkedin:
            entities.append(Entity("LinkedIn", f"https://www.linkedin.com/in/{linkedin.group(1)}"))
        order = list(LABEL_MAP.keys()) + ["linkedin_mirror"]
        entities.sort(
            key=lambda entity: order.index(_rev_label(entity.label))
            if _rev_label(entity.label) in order
            else len(order)
        )
        entities = derive_entities(entities)

        finished = time.perf_counter()
        return ExtractionResult(
            entities=entities,
            source="gliner+regex",
            timings_ms={
                "load_or_warmup": round((loaded_at - started) * 1000, 1),
                "infer": round((inferred_at - loaded_at) * 1000, 1),
                "total": round((finished - started) * 1000, 1),
            },
        )


def _rev_label(label: str) -> str:
    if label == "LinkedIn":
        return "linkedin_mirror"
    for key, mapped in LABEL_MAP.items():
        if mapped == label:
            return key
    return "person_name"


def _normalize_value(key: str, value: str) -> str:
    value = value.strip().rstrip(",;")
    if key == "x_handle":
        match = X_URL_RE.search(value)
        if match:
            return f"@{match.group(1)}"
        return value if value.startswith("@") else f"@{value.lstrip('@')}"
    if key == "github":
        match = GITHUB_URL_RE.search(value)
        if match:
            return f"https://github.com/{match.group(1)}"
        if value.startswith("http"):
            return value
        return f"https://github.com/{value.lstrip('@')}"
    if key == "location":
        # Prefer a short city-like token when a region suffix is present.
        for sep in (" Bay Area", ",", "/"):
            if sep in value:
                return value.split(sep, 1)[0].strip()
        return value
    return value


def _merge_regex(text: str, by_key: dict[str, str]) -> None:
    if "email" not in by_key:
        match = EMAIL_RE.search(text)
        if match:
            by_key["email"] = match.group(0)
    if "phone" not in by_key:
        match = PHONE_RE.search(text)
        if match:
            by_key["phone"] = match.group(0)
    if "x_handle" not in by_key:
        match = X_URL_RE.search(text) or HANDLE_RE.search(text)
        if match:
            by_key["x_handle"] = f"@{match.group(1)}"
    if "github" not in by_key:
        match = GITHUB_URL_RE.search(text) or GITHUB_HANDLE_RE.search(text)
        if match:
            by_key["github"] = f"https://github.com/{match.group(1)}"


def _merge_line_kv(text: str, by_key: dict[str, str]) -> None:
    aliases = {
        "name": "person_name",
        "full name": "person_name",
        "email": "email",
        "phone": "phone",
        "mobile": "phone",
        "title": "job_title",
        "current position": "job_title",
        "position": "job_title",
        "role": "job_title",
        "company": "company",
        "employer": "company",
        "current employer": "company",
        "location": "location",
        "city": "location",
        "x": "x_handle",
        "twitter": "x_handle",
        "x profile": "x_handle",
        "github": "github",
        "website": "website",
        "date of birth": "date_of_birth",
        "dob": "date_of_birth",
    }
    for line in text.splitlines():
        match = LINE_KV.match(line)
        if not match:
            continue
        label = match.group(1).strip().casefold()
        value = match.group(2).strip()
        key = aliases.get(label)
        if key and key not in by_key and value:
            by_key[key] = _normalize_value(key, value)

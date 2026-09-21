"""Local persistence: the loaded resume PDF and remembered form answers.

Memory is a library of questions Harshil has answered, not a bag of strings.
Each entry keeps the question as it was asked, the answer, the field type,
every wording that has matched it, and when it was learned and last used.
"""

from __future__ import annotations

import io
import json
import os
import re
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from pypdf import PdfReader

DATA = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "oma-paster"
RESUME = DATA / "resume.pdf"
RESUME_TXT = DATA / "resume.txt"
META = DATA / "resume.json"
ANSWERS = DATA / "answers.json"
MAX_BYTES = 25 * 1024 * 1024


class ResumeError(Exception):
    pass


def _write_private(path: Path, data: bytes) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    path.chmod(0o600)


def pdf_text(data: bytes) -> str:
    try:
        reader = PdfReader(io.BytesIO(data))
        return "\n".join((page.extract_text() or "") for page in reader.pages).strip()
    except Exception as exc:  # noqa: BLE001 - pypdf raises many types
        raise ResumeError(f"Could not read that PDF: {exc}") from exc


def fetch(source: str) -> tuple[bytes, str]:
    """Return (pdf bytes, display name) from a local path or an http(s) URL."""
    source = source.strip()
    if re.match(r"^https?://", source, re.I):
        req = urllib.request.Request(source, headers={"User-Agent": "Mozilla/5.0 oma-paster"})
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = resp.read(MAX_BYTES + 1)
        except OSError as exc:
            raise ResumeError(f"Could not download: {exc}") from exc
        name = source.rsplit("/", 1)[-1].split("?")[0] or "resume.pdf"
    else:
        path = Path(source.removeprefix("file://")).expanduser()
        if not path.is_file():
            raise ResumeError(f"No such file: {path}")
        data = path.read_bytes()
        name = path.name
    if len(data) > MAX_BYTES:
        raise ResumeError("PDF is larger than 25 MB.")
    if not data.startswith(b"%PDF"):
        raise ResumeError("That isn't a PDF (a link to a web page won't work — use the direct PDF link).")
    return data, name


def save_resume(data: bytes, name: str, source: str) -> str:
    text = pdf_text(data)
    if len(text) < 20:
        raise ResumeError("No selectable text in that PDF (scanned image?). OCR isn't supported yet.")
    RESUME_TXT.unlink(missing_ok=True)
    _write_private(RESUME, data)
    _write_private(META, json.dumps({"name": name, "source": source}).encode())
    return text


def save_text(text: str) -> str:
    text = text.strip()
    if len(text) < 20:
        raise ResumeError("That's too short to be a resume.")
    RESUME.unlink(missing_ok=True)
    _write_private(RESUME_TXT, text.encode())
    _write_private(META, json.dumps({"name": "pasted text", "source": "text"}).encode())
    return text


def current_resume() -> dict | None:
    if not (RESUME.is_file() or RESUME_TXT.is_file()):
        return None
    try:
        meta = json.loads(META.read_text())
    except (OSError, ValueError):
        meta = {}
    return {
        "name": meta.get("name", "resume"),
        "source": meta.get("source", ""),
        "path": str(RESUME) if RESUME.is_file() else None,
    }


def resume_text() -> str:
    if RESUME.is_file():
        return pdf_text(RESUME.read_bytes())
    return RESUME_TXT.read_text() if RESUME_TXT.is_file() else ""


def clear_resume() -> None:
    """Remove the resume and every profile value derived from or edited beside it."""
    for f in (RESUME, RESUME_TXT, META, PROFILE, MANUAL):
        f.unlink(missing_ok=True)


def norm(label: str) -> str:
    """Stable lookup key: lowercase, punctuation stripped, whitespace collapsed."""
    text = re.sub(r"[^a-z0-9 ]+", "", label.lower().replace("*", ""))
    return re.sub(r"\s+", " ", text).strip()


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _coerce(key: str, rec: object) -> dict | None:
    """Accept the old flat record and the current one. Drop anything unusable."""
    if isinstance(rec, str):
        rec = {"q": key, "a": rec}
    if not isinstance(rec, dict):
        return None
    question = str(rec.get("q") or key).strip()
    answer = str(rec.get("a") if rec.get("a") is not None else "").strip()
    if not question or not answer:
        return None
    seen = rec.get("wordings") or rec.get("aliases") or []
    if isinstance(seen, str):
        seen = [seen]
    wordings = []
    for wording in [*seen, question]:
        wording = str(wording).strip()
        if wording and wording not in wordings:
            wordings.append(wording)
    # the question as last asked leads the list; older wordings follow
    if question in wordings:
        wordings.remove(question)
    wordings.insert(0, question)
    created = str(rec.get("created") or "")
    updated = str(rec.get("updated") or created)
    # n counts uses. Older files stored the count already including the save itself,
    # and remember() adds one whenever it rewrites an entry — including on a plain load.
    # Keep the stored count; only a genuinely new answer starts at 1.
    return {
        "q": question,
        "a": answer,
        "type": str(rec.get("type") or ""),
        "n": max(1, int(rec.get("n") or 1)),
        "wordings": wordings[:12],
        "created": created,
        "updated": updated,
    }


def load_answers() -> dict[str, dict]:
    """norm(question) -> memory entry. Older files (no dates, no wordings) still load."""
    try:
        raw = json.loads(ANSWERS.read_text())
    except (OSError, ValueError):
        return {}
    if not isinstance(raw, dict):
        return {}
    out = {}
    for key, rec in raw.items():
        entry = _coerce(str(key), rec)
        if not entry:
            continue
        # keep the key already on disk so older files (looser spacing) still round-trip
        stored = str(key).strip() or norm(entry["q"])
        out[stored] = entry
    return out


def _save_answers(answers: dict[str, dict]) -> None:
    _write_private(ANSWERS, json.dumps(answers, indent=2, sort_keys=True, ensure_ascii=False).encode())


def clear_answers() -> None:
    ANSWERS.unlink(missing_ok=True)


def _find_key(answers: dict[str, dict], key: str) -> str | None:
    if key in answers:
        return key
    wanted = norm(key)
    hits = [k for k in answers if norm(k) == wanted]
    return hits[0] if hits else None


def delete_answer(key: str) -> None:
    answers = load_answers()
    found = _find_key(answers, key)
    if found is not None and answers.pop(found, None) is not None:
        _save_answers(answers)


def update_answer(key: str, *, answer: str | None = None, question: str | None = None) -> dict | None:
    """Edit a remembered answer (and optionally the question it is filed under)."""
    answers = load_answers()
    current_key = _find_key(answers, key)
    if current_key is None:
        return None
    entry = answers[current_key]
    if answer is not None:
        answer = answer.strip()
        if not answer:
            return None
        entry["a"] = answer
    if question is not None and question.strip():
        question = question.strip()
        if question not in entry["wordings"]:
            entry["wordings"].insert(0, question)
        entry["q"] = question
        new_key = norm(question)
        if new_key and new_key != current_key and new_key not in answers:
            answers.pop(current_key, None)
            current_key = new_key
        # if that wording is already its own memory, keep this entry where it is.
        # editing does not count as another use.
    entry["updated"] = _now()
    answers[current_key] = entry
    _save_answers(answers)
    return {"key": current_key, **entry}


def remember(label: str, value: str, ftype: str = "") -> bool:
    """File an answer under its question. True only when the stored answer actually changed."""
    label, value = label.strip(), value.strip()
    key = norm(label)
    if not key or not value:
        return False
    answers = load_answers()
    now = _now()
    # match on the normalized question, not the raw stored key (older files kept looser spacing)
    key = _find_key(answers, key) or key
    prev = answers.get(key)
    if prev is None:
        answers[key] = {
            "q": label, "a": value, "type": ftype, "n": 1,
            "wordings": [label], "created": now, "updated": now,
        }
        changed = True
    else:
        wordings = list(prev.get("wordings") or [prev["q"]])
        changed = prev.get("a") != value or label not in wordings
        if label not in wordings:
            wordings.append(label)
        answers[key] = {
            "q": label,  # the wording seen most recently is the one shown first
            "a": value,
            "type": ftype or prev.get("type") or "",
            "n": int(prev.get("n", 0)) + (1 if changed else 0),
            "wordings": wordings[:12],
            "created": prev.get("created") or now,
            "updated": now if changed else prev.get("updated") or now,
        }
    if changed:
        _save_answers(answers)
    return changed


PROFILE = DATA / "profile.json"


def save_profile(entities: list[dict[str, str]]) -> None:
    _write_private(PROFILE, json.dumps(entities, indent=2, ensure_ascii=False).encode())


def load_profile() -> list[dict[str, str]] | None:
    try:
        return json.loads(PROFILE.read_text())
    except (OSError, ValueError):
        return None


MANUAL = DATA / "profile_manual.json"


def load_manual() -> dict[str, str]:
    """Profile values the user typed by hand; a re-read resume never overrides these."""
    try:
        return json.loads(MANUAL.read_text())
    except (OSError, ValueError):
        return {}


def save_manual(values: dict[str, str]) -> None:
    _write_private(MANUAL, json.dumps(values, indent=2, ensure_ascii=False).encode())


def clear_all() -> None:
    """Remove all locally persisted application data, but not downloaded model caches."""
    clear_resume()
    clear_answers()

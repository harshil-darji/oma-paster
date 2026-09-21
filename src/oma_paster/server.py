"""oma-paster backend: resume → profile → live job page (via Playwright)."""

from __future__ import annotations

import asyncio
import os
import re
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from cua_s1.schema import Entity
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import platform
import sys
import time
from importlib import metadata

from oma_paster import settings as cfg
from oma_paster import similar, store
from oma_paster import theme as theme_mod
from oma_paster.decide import CuaS1Backend
from oma_paster.extract import Extractor
from oma_paster.jobs import TEXT_TYPES, JobSession

STATIC = Path(__file__).resolve().parents[2] / "static"


MODEL_META = {
    "extractor": ("Resume reader", "Pulls name, email, phone… out of your resume (GLiNER)"),
    "scorer": ("Field matcher", "Decides which resume detail belongs in which form field (cua-s1)"),
    "matcher": ("Question memory", "Recognises reworded questions you've answered before"),
}


class Slot:
    def __init__(self, key: str, model_id: str) -> None:
        self.key, self.model_id = key, model_id
        self.status = "pending"  # pending | loading | ready | error
        self.started = 0.0
        self.seconds: float | None = None
        self.cached: bool | None = None
        self.error = ""
        self.note = ""

    def public(self) -> dict[str, Any]:
        role, blurb = MODEL_META[self.key]
        elapsed = round(time.time() - self.started, 1) if self.status == "loading" else self.seconds
        return {"key": self.key, "role": role, "blurb": blurb, "model_id": self.model_id, "status": self.status,
                "seconds": elapsed, "cached": self.cached, "error": self.error, "note": self.note}


def _is_cached(repo_id: str) -> bool:
    try:
        from huggingface_hub import snapshot_download

        snapshot_download(repo_id, local_files_only=True)
        return True
    except Exception:  # noqa: BLE001
        return False


class AppState:
    def __init__(self) -> None:
        self.settings = cfg.load()
        self.device = os.environ.get("OMA_PASTER_DEVICE") or self.settings["device"]
        self.extractor = Extractor(self.settings["extractor_model"], device=self.device)
        self.scorer = CuaS1Backend(device=self.device)
        self.matcher = similar.Matcher(self.settings["matcher_model"])
        self.entities: list[Entity] = []
        self.job = JobSession()
        self.ready = {"extractor": False, "scorer": False}
        self.slots = {
            "extractor": Slot("extractor", self.settings["extractor_model"]),
            "scorer": Slot("scorer", self.scorer.repo_id),
            "matcher": Slot("matcher", self.settings["matcher_model"]),
        }

    def entity_dicts(self) -> list[dict[str, str]]:
        return [{"label": e.label, "value": e.value} for e in self.entities]


state = AppState()


async def _ingest(text: str) -> None:
    result = await asyncio.to_thread(state.extractor.extract, text)
    manual = store.load_manual()
    kept = [e for e in result.entities if e.label not in manual]
    state.entities = kept + [Entity(k, v) for k, v in manual.items()]
    store.save_profile(state.entity_dicts())


def _preimport() -> None:
    """transformers' lazy imports aren't thread-safe; import everything once before loading models in parallel."""
    import cua_s1.model  # noqa: F401
    import gliner2  # noqa: F401
    import transformers
    from transformers import AutoConfig, AutoModel, AutoTokenizer  # noqa: F401

    _ = transformers.AutoModel


async def _load_slot(key: str, *, fresh: bool = False) -> None:
    """(Re)load one model, tracking status for the UI. On a failed switch the previous model stays in use."""
    slot = state.slots[key]
    settings = state.settings
    old = getattr(state, key)
    previously_ready = slot.status == "ready"
    slot.model_id = {"extractor": settings["extractor_model"], "matcher": settings["matcher_model"], "scorer": slot.model_id}[key]
    slot.status, slot.started, slot.error, slot.note = "loading", time.time(), "", ""
    slot.cached = await asyncio.to_thread(_is_cached, slot.model_id)
    try:
        if fresh:
            new = {
                "extractor": lambda: Extractor(slot.model_id, device=state.device),
                "scorer": lambda: CuaS1Backend(device=state.device),
                "matcher": lambda: similar.Matcher(slot.model_id),
            }[key]()
        else:
            new = old
        await asyncio.to_thread(new.ensure_loaded)
        setattr(state, key, new)
        slot.status, slot.seconds = "ready", round(time.time() - slot.started, 1)
        if key in state.ready:
            state.ready[key] = True
    except Exception as exc:  # noqa: BLE001
        msg = str(exc).splitlines()[0][:220] if str(exc) else exc.__class__.__name__
        if previously_ready and fresh:
            slot.status, slot.note = "ready", f"Switch failed ({msg}) — still using the previous model."
            slot.model_id = getattr(old, "model_id", slot.model_id)
        else:
            slot.status, slot.error = "error", msg
    slot.seconds = slot.seconds if slot.status == "ready" else round(time.time() - slot.started, 1)


@asynccontextmanager
async def lifespan(app: FastAPI):
    async def warm() -> None:
        async def extractor_then_profile() -> None:
            await _load_slot("extractor")
            saved = store.load_profile()
            if saved is not None:
                state.entities = [Entity(e["label"], e["value"]) for e in saved]
            elif store.current_resume() and state.ready["extractor"]:
                await _ingest(await asyncio.to_thread(store.resume_text))

        await asyncio.to_thread(_preimport)
        # load all three at once — first-run downloads overlap instead of queueing
        await asyncio.gather(extractor_then_profile(), _load_slot("scorer"), _load_slot("matcher"))

    task = asyncio.create_task(warm())
    yield
    task.cancel()
    await state.job.close()


app = FastAPI(title="oma-paster", lifespan=lifespan)


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/api/theme")
async def theme() -> dict[str, Any]:
    return await asyncio.to_thread(theme_mod.load)


def _profile() -> dict[str, Any]:
    cur = store.current_resume()
    return {
        "ready": all(state.ready.values()),
        "resume": {"name": cur["name"], "pdf": bool(cur["path"])} if cur else None,
        "entities": state.entity_dicts(),
        "saved_answers": len(store.load_answers()),
    }


def _version(pkg: str) -> str:
    try:
        return metadata.version(pkg)
    except metadata.PackageNotFoundError:
        return "?"


def _system() -> dict[str, Any]:
    import torch

    from oma_paster.jobs import _chromium

    return {
        "app_version": _version("oma-paster"),
        "python": sys.version.split()[0],
        "torch": torch.__version__.split("+")[0],
        "cuda": torch.cuda.is_available(),
        "device": state.device,
        "playwright": _version("playwright"),
        "browser": _chromium() or "not found",
        "platform": f"{platform.system()} {platform.release()}",
        "data_dir": str(store.DATA),
        "theme": theme_mod.current_name() or "unknown",
    }


@app.get("/api/status")
async def status() -> dict[str, Any]:
    return {
        "models": [s.public() for s in state.slots.values()],
        "ready": all(state.ready.values()),
        "settings": cfg.load(),
        "options": cfg.OPTIONS,
        "cuda": _cuda(),
    }


def _cuda() -> bool:
    import torch

    return torch.cuda.is_available()


@app.get("/api/about")
async def about() -> dict[str, Any]:
    return await asyncio.to_thread(_system)


@app.put("/api/settings")
async def settings_update(patch: dict[str, Any]) -> dict[str, Any]:
    before = cfg.load()
    state.settings = cfg.update(patch)
    if patch.get("device") in ("cpu", "cuda") and state.settings["device"] != before["device"]:
        import torch

        if patch["device"] == "cuda" and not torch.cuda.is_available():
            state.settings["device"] = before["device"]
            cfg.update({"device": before["device"]})
        else:
            state.device = state.settings["device"]
            for key in ("extractor", "scorer"):
                asyncio.create_task(_load_slot(key, fresh=True))
    if state.settings["extractor_model"] != before["extractor_model"]:
        asyncio.create_task(_load_slot("extractor", fresh=True))
    if state.settings["matcher_model"] != before["matcher_model"]:
        asyncio.create_task(_load_slot("matcher", fresh=True))
    return await status()


@app.get("/api/profile")
async def profile() -> dict[str, Any]:
    return _profile()


@app.get("/resume.pdf")
async def resume_pdf() -> FileResponse:
    return FileResponse(store.RESUME, media_type="application/pdf")


# ---- resume ----------------------------------------------------------------


class ResumeSource(BaseModel):
    source: str


class ResumeText(BaseModel):
    text: str


async def _resume_saved(saver, *args) -> JSONResponse:
    if not state.ready["extractor"]:
        return JSONResponse({"ok": False, "error": "Still loading the models — try again in a few seconds."}, status_code=503)
    try:
        text = await asyncio.to_thread(saver, *args)
        await _ingest(text)
    except store.ResumeError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
    return JSONResponse({"ok": True, **_profile()})


@app.post("/api/resume/load")
async def resume_load(body: ResumeSource) -> JSONResponse:
    try:
        data, name = await asyncio.to_thread(store.fetch, body.source)
    except store.ResumeError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
    return await _resume_saved(store.save_resume, data, name, body.source.strip())


@app.put("/api/resume/upload")
async def resume_upload(request: Request) -> JSONResponse:
    data = await request.body()
    if not data.startswith(b"%PDF"):
        return JSONResponse({"ok": False, "error": "That isn't a PDF."}, status_code=400)
    return await _resume_saved(store.save_resume, data, request.headers.get("x-filename", "resume.pdf"), "upload")


@app.post("/api/resume/text")
async def resume_text(body: ResumeText) -> JSONResponse:
    return await _resume_saved(store.save_text, body.text)


@app.post("/api/resume/reset")
async def resume_reset() -> dict[str, Any]:
    store.clear_resume()
    state.entities = []
    return _profile()


@app.post("/api/data/clear")
async def data_clear() -> dict[str, Any]:
    """Erase all personal application data; model downloads are intentionally retained."""
    store.clear_all()
    cfg.PATH.unlink(missing_ok=True)
    state.entities = []
    state.settings = cfg.load()
    await state.job.close()
    return {"ok": True, **_profile()}


class ProfileEdit(BaseModel):
    entities: list[dict[str, str]]


@app.put("/api/profile")
async def profile_edit(body: ProfileEdit) -> dict[str, Any]:
    before = {e.label: e.value for e in state.entities}
    state.entities = [Entity(e["label"], e["value"]) for e in body.entities if e.get("value", "").strip()]
    manual = store.load_manual()
    for e in state.entities:
        if before.get(e.label) != e.value:
            manual[e.label] = e.value
    store.save_manual(manual)
    store.save_profile(state.entity_dicts())
    return _profile()


def _answer_rows() -> list[dict[str, Any]]:
    rows = [{"key": k, **v} for k, v in store.load_answers().items()]
    rows.sort(key=lambda r: (r.get("updated") or r.get("created") or "", r["q"].lower()), reverse=True)
    return rows


@app.get("/api/answers")
async def answers_list() -> dict[str, Any]:
    return {"answers": _answer_rows()}


class AnswerEdit(BaseModel):
    answer: str | None = None
    question: str | None = None


@app.put("/api/answers/{key}")
async def answers_edit(key: str, body: AnswerEdit) -> JSONResponse:
    updated = store.update_answer(key, answer=body.answer, question=body.question)
    if updated is None:
        return JSONResponse({"ok": False, "error": "That memory isn't there, or the answer was empty."}, status_code=404)
    return JSONResponse({"ok": True, "answer": updated, "saved_answers": len(store.load_answers())})


@app.delete("/api/answers/{key}")
async def answers_delete(key: str) -> dict[str, Any]:
    store.delete_answer(key)
    return _profile()


@app.post("/api/answers/clear")
async def answers_clear() -> dict[str, Any]:
    store.clear_answers()
    return _profile()


# ---- job link --------------------------------------------------------------


class JobOpen(BaseModel):
    url: str


class JobField(BaseModel):
    id: str
    value: str
    remember: bool = True


SIMILAR_TYPES = TEXT_TYPES | {"combobox", "textarea", "select", "radio"}


async def _suggest(fields: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Propose values: exact saved answer → resume file → resume entity → similar saved question."""
    answers = store.load_answers()
    resume = store.current_resume()
    out: dict[str, dict[str, Any]] = {}
    candidates, leftovers = [], []
    for f in fields:
        label = f["label"]
        if f["type"] == "file":
            if resume and resume["path"] and re.search(r"resume|cv|curriculum", label, re.I):
                out[f["id"]] = {"value": resume["path"], "source": "resume"}
            continue
        saved = answers.get(store.norm(label))
        if saved:
            out[f["id"]] = {"value": saved["a"], "source": "saved"}
        elif f["type"] in TEXT_TYPES or f["type"] == "combobox":
            candidates.append(f)
        elif f["type"] in SIMILAR_TYPES and not f.get("single"):
            leftovers.append(f)
    if candidates and state.entities:
        planned = await asyncio.to_thread(
            state.scorer.fill_map,
            "Job application",
            [{"id": f["id"], "label": f["label"], "role": "Edit", "value": ""} for f in candidates],
            state.entities,
            min_confidence=0.75,  # cua-s1 scores real matches ~1.0; wrong ones (e.g. "Notice period"→Employer) ~0.55
        )
        for fid, value in planned["fills"].items():
            out[fid] = {"value": value, "source": "resume"}
    leftovers += [f for f in candidates if f["id"] not in out and f["type"] in SIMILAR_TYPES]
    if answers:
        for f in leftovers:
            hit = await asyncio.to_thread(state.matcher.best, f["label"], answers)
            if hit:
                rec, score = hit
                out[f["id"]] = {"value": rec["a"], "source": "similar", "from": rec["q"], "score": round(score, 2)}
    state.job.suggested = {k: v["value"] for k, v in out.items()}
    state.job.sources = {k: v["source"] for k, v in out.items()}
    return out


def _alnum(v: str) -> str:
    return re.sub(r"[^a-z0-9]", "", v.lower())


async def _learn() -> int:
    """Remember what's really in the page: answers typed in the browser or edited in the app."""
    learned = 0
    values = await state.job.read_values()
    for f in state.job.fields:
        v = values.get(f["id"], "").strip()
        if not v or f["type"] == "file" or f.get("single"):
            continue
        # untouched suggestions aren't "learned" (sites may reformat, e.g. phone masks)
        if _alnum(v) == _alnum(state.job.suggested.get(f["id"], "")):
            continue
        store.remember(f["label"], v, f["type"])
        learned += 1
    return learned


async def _job_payload(scan: dict[str, Any], *, autofill: bool = True) -> dict[str, Any]:
    suggestions = await _suggest(scan["fields"])
    # similar-question matches are only shown, never pasted, until the user confirms them
    sure = {k: v["value"] for k, v in suggestions.items() if v["source"] != "similar"}
    errors = await state.job.apply(sure) if autofill else {}
    return {"ok": True, **scan, "suggestions": suggestions, "errors": errors}


@app.post("/api/job/open")
async def job_open(body: JobOpen) -> JSONResponse:
    if not all(state.ready.values()):
        return JSONResponse({"ok": False, "error": "Still loading the models — try again in a few seconds."}, status_code=503)
    try:
        scan = await state.job.open(body.url)
        return JSONResponse(await _job_payload(scan))
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "error": str(exc).splitlines()[0]}, status_code=400)


@app.post("/api/job/rescan")
async def job_rescan() -> JSONResponse:
    await _learn()
    return JSONResponse(await _job_payload(await state.job.scan()))


@app.post("/api/job/field")
async def job_field(body: JobField) -> dict[str, Any]:
    errors = await state.job.apply({body.id: body.value})
    f = next((f for f in state.job.fields if f["id"] == body.id), None)
    confirmed_similar = state.job.sources.get(body.id) == "similar"
    remembered = False
    if (
        f and body.remember and f["type"] != "file" and not f.get("single") and not errors
        and (confirmed_similar or body.value != state.job.suggested.get(body.id))
    ):
        remembered = store.remember(f["label"], body.value, f["type"])  # also teaches the new wording
        state.job.sources[body.id] = "saved"
        state.job.suggested[body.id] = body.value
    return {"ok": not errors, "errors": errors, "remembered": remembered, "captcha": await state.job.captcha()}


@app.post("/api/job/submit")
async def job_submit() -> JSONResponse:
    await _learn()
    try:
        result = await state.job.submit()
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "message": str(exc).splitlines()[0]}, status_code=400)
    if result.get("next_step"):
        result = await _job_payload(result) | {"next_step": True}
    return JSONResponse(result)


@app.get("/api/job/status")
async def job_status() -> dict[str, Any]:
    page = state.job.page
    return {"open": bool(page and not page.is_closed()), "captcha": await state.job.captcha()}


@app.post("/api/job/close")
async def job_close() -> dict[str, Any]:
    await state.job.close()
    return {"ok": True}


app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")


def main() -> None:
    import uvicorn

    uvicorn.run("oma_paster.server:app", host="127.0.0.1", port=8787, reload=False)


if __name__ == "__main__":
    main()

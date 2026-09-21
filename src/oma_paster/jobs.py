"""Drive a real job-application page in a visible browser: scan → suggest → fill → submit.

Nothing is submitted without an explicit call, and captchas are never solved
automatically — the human solves them in the browser window.
"""

from __future__ import annotations

import asyncio
import base64
import os
import re
import shutil
import socket
from typing import Any

from playwright.async_api import Frame, Page, async_playwright

from oma_paster import store

PROFILE = store.DATA / "browser"

SCAN_JS = r"""
(prefix) => {
  const txt = (n) => ((n && n.textContent) || '').replace(/\s+/g, ' ').trim();
  const shown = (el) => {
    const r = el.getBoundingClientRect(), s = getComputedStyle(el);
    return s.visibility !== 'hidden' && s.display !== 'none' && (r.width > 0 || r.height > 0);
  };
  const ownLabel = (el) => {
    const al = el.getAttribute('aria-label'); if (al) return al.trim();
    const by = el.getAttribute('aria-labelledby');
    if (by) { const t = by.split(/\s+/).map(i => txt(document.getElementById(i))).join(' ').trim(); if (t) return t; }
    if (el.id) { const l = document.querySelector('label[for="' + CSS.escape(el.id) + '"]'); if (l) return txt(l); }
    const w = el.closest('label'); if (w) return txt(w);
    return '';
  };
  const groupLabel = (el) => {
    const fs = el.closest('fieldset'); const lg = fs && fs.querySelector('legend'); if (lg) return txt(lg);
    const grp = el.closest('[role=radiogroup],[role=group]');
    if (grp) { const a = grp.getAttribute('aria-label'); if (a) return a;
      const by = grp.getAttribute('aria-labelledby'); if (by) return txt(document.getElementById(by)); }
    for (let s = el.previousElementSibling; s; s = s.previousElementSibling) {
      if (!s.querySelector('input,select,textarea') && s.tagName !== 'INPUT' && txt(s).length > 1 && txt(s).length < 300) return txt(s);
    }
    let node = el;
    for (let i = 0; i < 5 && node.parentElement; i++) {
      node = node.parentElement;
      for (let s = node.previousElementSibling; s; s = s.previousElementSibling) {
        if (!s.querySelector('input,select,textarea') && txt(s).length > 2 && txt(s).length < 300) return txt(s);
      }
      const lab = node.querySelector(':scope > label, :scope > legend, :scope > [class*=label], :scope > h3, :scope > h4');
      if (lab && !lab.contains(el) && txt(lab).length > 2) return txt(lab);
    }
    return '';
  };
  const fields = [], groups = {};
  let n = 0;
  const tag = (el) => { const id = prefix + (n++); el.setAttribute('data-omap', id); return id; };
  for (const el of document.querySelectorAll('input,select,textarea')) {
    const t = (el.getAttribute('type') || (el.tagName === 'SELECT' ? 'select' : el.tagName === 'TEXTAREA' ? 'textarea' : 'text')).toLowerCase();
    if (['hidden','submit','button','image','reset','password'].includes(t)) continue;
    if (/g-recaptcha-response|h-captcha-response|cf-turnstile-response/.test(el.name || el.id || '')) continue;
    if (el.disabled || el.getAttribute('aria-hidden') === 'true') continue;
    if (t !== 'file' && !shown(el) && !(t === 'radio' || t === 'checkbox')) continue;
    { const r = el.getBoundingClientRect(); if (r.right < 0 || r.bottom < 0 || r.left > innerWidth + 50) continue; }
    if (el.closest('.grecaptcha-badge,[class*=honeypot],[class*=hp-]')) continue;
    const required = el.required || el.getAttribute('aria-required') === 'true';
    if (t === 'radio' || t === 'checkbox') {
      const key = t + ':' + (el.name || groupLabel(el) || n);
      const optLabel = ownLabel(el) || el.value;
      let g = groups[key];
      if (!g) {
        g = groups[key] = { id: tag(el), label: groupLabel(el), type: t, options: [], required };
        fields.push(g);
      }
      const oid = el.getAttribute('data-omap') || tag(el);
      g.options.push({ id: oid, label: optLabel, checked: el.checked });
      continue;
    }
    let opts = [];
    if (t === 'select') opts = [...el.options].filter(o => o.value !== '' && !/^(select|choose|--)/i.test(o.text.trim())).map(o => o.text.trim());
    const role = el.getAttribute('role');
    fields.push({
      id: tag(el), type: role === 'combobox' ? 'combobox' : t, options: opts, required,
      label: ownLabel(el) || groupLabel(el) || el.placeholder || el.name || '',
      value: t === 'file' ? '' : (el.value || ''), placeholder: el.placeholder || '',
    });
  }
  for (const f of fields) {
    if (f.type === 'checkbox' && f.options.length === 1 && f.options[0].label) {
      f.label = f.options[0].label; f.single = true;
    } else if ((f.type === 'radio' || f.type === 'checkbox') && !f.label) {
      f.label = f.options.map(o => o.label).join(' / ');
    }
    if (/\*/.test(f.label || '')) f.required = true;
    f.label = (f.label || '').replace(/\s*\*\s*$/, '').trim();
  }
  return fields;
}
"""

CAPTCHA_JS = r"""
() => {
  const widgets = [...document.querySelectorAll(
    'iframe[src*="recaptcha/api2/anchor"], iframe[src*="hcaptcha.com"], iframe[src*="challenges.cloudflare.com"], .cf-turnstile, .h-captcha, .g-recaptcha')]
    .filter(w => !w.closest('.grecaptcha-badge') && !/size=invisible/.test(w.getAttribute('src') || '') && !(w.dataset && w.dataset.size === 'invisible'))
    .filter(w => { const r = w.getBoundingClientRect(); return r.width > 20 && r.height > 20; });
  const tokens = [...document.querySelectorAll('[name="g-recaptcha-response"],[name="h-captcha-response"],[name="cf-turnstile-response"]')];
  const challenge = [...document.querySelectorAll('iframe[src*="recaptcha/api2/bframe"], iframe[src*="hcaptcha.com/captcha"][style*="visible"]')]
    .some(w => { const r = w.getBoundingClientRect(); return r.width > 100 && r.height > 100 && getComputedStyle(w).visibility !== 'hidden'; });
  return { present: widgets.length > 0, solved: tokens.some(t => (t.value || '').length > 20), challenge };
}
"""

FIELD_ERRORS_JS = r"""
() => [...document.querySelectorAll('[aria-invalid="true"], input:invalid, select:invalid, textarea:invalid')]
  .filter(e => e.getAttribute('data-omap')).map(e => e.getAttribute('data-omap'))
"""

TEXT_TYPES = {"text", "email", "tel", "url", "number", "search"}
SUBMIT_RE = re.compile(r"^\s*(submit|apply|send)\b", re.I)
NEXT_RE = re.compile(r"^\s*(next|continue|save and continue)\b", re.I)
SUCCESS_RE = re.compile(r"thank you|application (has been )?(received|submitted)|successfully submitted|we.ve received", re.I)


def _chromium() -> str | None:
    return os.environ.get("OMA_PASTER_CHROMIUM") or shutil.which("chromium") or shutil.which("google-chrome-stable")


def _fuzzy(options: list[str], value: str) -> str | None:
    v = value.strip().lower()
    for o in options:
        if o.strip().lower() == v:
            return o
    for o in options:
        if v and (v in o.lower() or o.lower() in v):
            return o
    return None


class JobSession:
    def __init__(self) -> None:
        self._pw = None
        self._ctx = None
        self._browser = None
        self._proc = None
        self.page: Page | None = None
        self.fields: list[dict[str, Any]] = []
        self.frames: dict[str, Frame] = {}
        self.suggested: dict[str, str] = {}
        self.sources: dict[str, str] = {}

    async def _ensure(self) -> Page:
        if self.page and not self.page.is_closed():
            return self.page
        if self._browser is not None and not self._browser.is_connected():
            await self.close()
        if self._ctx is None:
            self._ctx = await self._attach()
        self.page = await self._ctx.new_page()
        return self.page

    async def _attach(self):
        """Start a normal Chromium (no automation flags) and connect to it over CDP."""
        exe = _chromium()
        if not exe:
            raise RuntimeError("Chromium not found; set OMA_PASTER_CHROMIUM")
        PROFILE.mkdir(parents=True, exist_ok=True)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        cmd = [exe, f"--user-data-dir={PROFILE}", f"--remote-debugging-port={port}",
               "--remote-debugging-address=127.0.0.1", "--no-first-run", "--no-default-browser-check",
               "--ozone-platform-hint=auto", "about:blank"]
        if os.environ.get("OMA_PASTER_HEADLESS"): 
            cmd.insert(1, "--headless=new")
        self._proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        self._pw = await async_playwright().start()
        for _ in range(60):
            if self._proc.returncode is not None:
                raise RuntimeError("Chromium exited; close other windows using the oma-paster profile and retry")
            try:
                browser = await self._pw.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
                break
            except Exception:
                await asyncio.sleep(0.25)
        else:
            raise RuntimeError("Could not connect to Chromium")
        self._browser = browser
        return browser.contexts[0]

    async def close(self) -> None:
        try:
            if self._browser:
                await self._browser.close()
        except Exception:
            pass
        if self._proc and self._proc.returncode is None:
            self._proc.terminate()
        if self._pw:
            await self._pw.stop()
        self._ctx = self._pw = self.page = self._browser = self._proc = None

    async def open(self, url: str) -> dict[str, Any]:
        if not re.match(r"^https?://", url, re.I):
            url = "https://" + url
        page = await self._ensure()
        await page.goto(url, wait_until="domcontentloaded", timeout=45000)
        await page.wait_for_timeout(1500)  # let SPA forms mount
        return await self.scan()

    async def scan(self) -> dict[str, Any]:
        page = await self._ensure()
        self.fields, self.frames = [], {}
        for i, frame in enumerate(page.frames):
            try:
                found = await frame.evaluate(SCAN_JS, f"f{i}_")
            except Exception:  # noqa: BLE001 - detached/cross-origin frames
                continue
            for f in found:
                self.frames[f["id"]] = frame
                for o in f.get("options", []) if isinstance(f.get("options"), list) else []:
                    if isinstance(o, dict):
                        self.frames[o["id"]] = frame
            self.fields.extend(found)
        return {
            "url": page.url,
            "title": await page.title(),
            "fields": self.fields,
            "captcha": await self.captcha(),
        }

    async def captcha(self) -> dict[str, bool]:
        page = self.page
        state = {"present": False, "solved": False, "challenge": False}
        if not page or page.is_closed():
            return state
        for frame in page.frames:
            try:
                s = await frame.evaluate(CAPTCHA_JS)
            except Exception:  # noqa: BLE001
                continue
            state["present"] |= s["present"]
            state["solved"] |= s["solved"]
            state["challenge"] |= s["challenge"]
        return state

    # ---- applying values -------------------------------------------------
    async def apply(self, values: dict[str, Any]) -> dict[str, str]:
        """Write values into the live page. Returns {field_id: error} for failures."""
        errors: dict[str, str] = {}
        by_id = {f["id"]: f for f in self.fields}
        for fid, raw in values.items():
            f = by_id.get(fid)
            if not f or raw in (None, ""):
                continue
            frame = self.frames.get(fid)
            if frame is None:
                continue
            try:
                await self._apply_one(frame, f, str(raw))
            except Exception as exc:  # noqa: BLE001
                errors[fid] = str(exc).splitlines()[0][:160]
        return errors

    async def _apply_one(self, frame: Frame, f: dict[str, Any], value: str) -> None:
        loc = frame.locator(f'[data-omap="{f["id"]}"]')
        t = f["type"]
        if t in TEXT_TYPES or t in {"textarea", "date"}:
            await loc.fill(value, timeout=5000)
        elif t == "combobox":
            await loc.fill(value, timeout=5000)
            opt = frame.get_by_role("option", name=re.compile(re.escape(value), re.I)).first
            try:
                await opt.click(timeout=2500)
            except Exception:  # noqa: BLE001
                await loc.press("Enter")
        elif t == "select":
            match = _fuzzy(f["options"], value)
            if not match:
                raise ValueError(f"no option matches '{value}'")
            await loc.select_option(label=match, timeout=5000)
        elif t == "file":
            await loc.set_input_files(value, timeout=5000)
        elif t in {"radio", "checkbox"}:
            wanted = [v.strip() for v in value.split(";") if v.strip()] if t == "checkbox" and not f.get("single") else [value]
            if f.get("single"):
                on = value.strip().lower() in {"true", "yes", "y", "1", "on", "checked"}
                target = frame.locator(f'[data-omap="{f["options"][0]["id"]}"]')
                await (target.check(force=True, timeout=5000) if on else target.uncheck(force=True, timeout=5000))
                return
            labels = [o["label"] for o in f["options"]]
            for w in wanted:
                m = _fuzzy(labels, w)
                if not m:
                    raise ValueError(f"no option matches '{w}'")
                oid = next(o["id"] for o in f["options"] if o["label"] == m)
                await frame.locator(f'[data-omap="{oid}"]').check(force=True, timeout=5000)

    async def read_values(self) -> dict[str, str]:
        """What is actually in the live page right now (includes things typed straight into the browser)."""
        out: dict[str, str] = {}
        for f in self.fields:
            frame = self.frames.get(f["id"])
            if frame is None or f["type"] == "file":
                continue
            try:
                t = f["type"]
                if t in {"radio", "checkbox"}:
                    picked = []
                    for o in f["options"]:
                        if await frame.locator(f'[data-omap="{o["id"]}"]').is_checked():
                            picked.append(o["label"])
                    out[f["id"]] = ("yes" if picked else "") if f.get("single") else "; ".join(picked)
                elif t == "select":
                    out[f["id"]] = await frame.locator(f'[data-omap="{f["id"]}"]').evaluate(
                        "e => e.selectedIndex > 0 ? e.options[e.selectedIndex].text.trim() : ''"
                    )
                else:
                    out[f["id"]] = await frame.locator(f'[data-omap="{f["id"]}"]').input_value(timeout=1500)
            except Exception:  # noqa: BLE001 - page changed under us
                continue
        return out

    # ---- submit ----------------------------------------------------------
    async def _find_button(self, pattern: re.Pattern[str]) -> tuple[Frame, str] | None:
        assert self.page
        for frame in self.page.frames:
            try:
                loc = frame.locator("button, input[type=submit], [role=button]")
                for i in range(await loc.count()):
                    b = loc.nth(i)
                    label = (await b.inner_text()) if await b.evaluate("e => e.tagName !== 'INPUT'") else await b.get_attribute("value")
                    if label and pattern.search(label) and await b.is_visible() and await b.is_enabled():
                        await b.evaluate("(e, i) => e.setAttribute('data-omap-btn', i)", "go")
                        return frame, label.strip()
            except Exception:  # noqa: BLE001
                continue
        return None

    async def submit(self) -> dict[str, Any]:
        page = await self._ensure()
        cap = await self.captcha()
        if cap["present"] and not cap["solved"]:
            await page.bring_to_front()
            return {"ok": False, "captcha": True, "message": "Solve the captcha in the browser window, then submit again."}
        found = await self._find_button(SUBMIT_RE)
        step = False
        if not found:
            found = await self._find_button(NEXT_RE)
            step = True
        if not found:
            return {"ok": False, "message": "Couldn't find a submit button — finish it in the browser window."}
        frame, label = found
        before = page.url
        await frame.locator('[data-omap-btn="go"]').first.click(timeout=5000)
        await page.wait_for_timeout(2500)
        for frame_ in page.frames:  # clean marker
            try:
                await frame_.evaluate("document.querySelectorAll('[data-omap-btn]').forEach(e => e.removeAttribute('data-omap-btn'))")
            except Exception:  # noqa: BLE001
                pass
        cap = await self.captcha()
        if cap["challenge"] or (cap["present"] and not cap["solved"]):
            await page.bring_to_front()
            return {"ok": False, "captcha": True, "message": "The site wants a captcha check — solve it in the browser window."}
        if step:
            return {"ok": True, "next_step": True, "clicked": label, **await self.scan()}
        body = (await page.inner_text("body"))[:4000]
        invalid: list[str] = []
        for frame_ in page.frames:
            try:
                invalid += await frame_.evaluate(FIELD_ERRORS_JS)
            except Exception:  # noqa: BLE001
                pass
        shot = base64.b64encode(await page.screenshot(type="jpeg", quality=60)).decode()
        return {
            "ok": True,
            "clicked": label,
            "url": page.url,
            "navigated": page.url != before,
            "success": bool(SUCCESS_RE.search(body)),
            "invalid": invalid,
            "screenshot": f"data:image/jpeg;base64,{shot}",
        }

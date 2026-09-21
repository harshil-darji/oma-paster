"""Read the active Omarchy theme so the UI can follow it.

The palette Omarchy last applied lives in
``~/.local/state/omarchy/current/theme/colors.toml`` — the same file
``omarchy theme set`` stages. Reading that (and noticing when it changes)
is what makes a theme switch show up here without asking the CLI.
"""

from __future__ import annotations

import subprocess
import tomllib
from pathlib import Path

HOME_THEMES = Path.home() / ".config/omarchy/themes"
STOCK_THEMES = Path("/usr/share/omarchy/themes")
APPLIED = Path.home() / ".local/state/omarchy/current/theme/colors.toml"
APPLIED_NAME = Path.home() / ".local/state/omarchy/current/theme.name"

# Every colour key shipped by all 22 stock themes, plus the few extras some
# themes add. Missing keys fall back so a partial colors.toml still paints.
FALLBACK = {
    "mode": "dark",
    "accent": "#7daea3",
    "selection": "#504945",
    "muted": "#665c54",
    "background": "#282828",
    "dark_background": "#1e1e1e",
    "darker_background": "#161616",
    "lighter_background": "#3c3836",
    "foreground": "#d4be98",
    "dark_foreground": "#7c6f64",
    "light_foreground": "#d4be98",
    "bright_foreground": "#d4be98",
    "red": "#ea6962",
    "yellow": "#d8a657",
    "green": "#a9b665",
    "cyan": "#89b482",
    "blue": "#7daea3",
    "magenta": "#d3869b",
    "orange": "#e78a4e",
    "brown": "#a67c52",
    "bright_red": "#ea6962",
    "bright_yellow": "#d8a657",
    "bright_green": "#a9b665",
    "bright_cyan": "#89b482",
    "bright_blue": "#7daea3",
    "bright_magenta": "#d3869b",
}


def current_name() -> str:
    """Display name of the applied theme. ``theme.name`` is the slug Omarchy wrote."""
    try:
        slug = APPLIED_NAME.read_text().strip()
    except OSError:
        slug = ""
    if slug:
        return slug.replace("-", " ").title()
    try:
        out = subprocess.run(["omarchy", "theme", "current"], capture_output=True, text=True, timeout=2)
        return out.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return ""


def _applied_colors() -> dict | None:
    try:
        data = tomllib.loads(APPLIED.read_text())
    except (OSError, tomllib.TOMLDecodeError):
        return None
    return data if isinstance(data, dict) and data.get("background") and data.get("foreground") else None


def _named_colors(name: str) -> dict | None:
    slug = name.lower().replace(" ", "-")
    for base in (HOME_THEMES, STOCK_THEMES):
        f = base / slug / "colors.toml"
        if not f.is_file():
            continue
        try:
            data = tomllib.loads(f.read_text())
        except (OSError, tomllib.TOMLDecodeError):
            return None
        return data if isinstance(data, dict) else None
    return None


def revision() -> str:
    """Changes when the applied theme file does, so the UI can refresh at once."""
    try:
        stat = APPLIED.stat()
    except OSError:
        return ""
    return f"{stat.st_mtime_ns}:{stat.st_size}"


def load() -> dict:
    name = current_name()
    colors = _applied_colors() or _named_colors(name) or {}
    merged = {**FALLBACK, **{k: v for k, v in colors.items() if isinstance(v, str) and v.strip()}}
    if merged.get("mode") not in ("light", "dark"):
        merged["mode"] = FALLBACK["mode"]
    return {"name": name or "fallback", "revision": revision(), "colors": merged}

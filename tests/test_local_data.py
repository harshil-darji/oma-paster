from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from oma_paster import settings, store, theme


@pytest.fixture
def local_data(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Point persistence modules at an isolated data directory."""
    data = tmp_path / "oma-paster"
    monkeypatch.setattr(store, "DATA", data)
    for name, filename in {
        "RESUME": "resume.pdf",
        "RESUME_TXT": "resume.txt",
        "META": "resume.json",
        "ANSWERS": "answers.json",
        "PROFILE": "profile.json",
        "MANUAL": "profile_manual.json",
    }.items():
        monkeypatch.setattr(store, name, data / filename)
    monkeypatch.setattr(settings, "PATH", data / "settings.json")
    return data


def test_resume_removal_clears_extracted_and_manual_profile(local_data: Path) -> None:
    store.save_text("Jon Doe\nSoftware engineer with enough text for a resume.")
    store.save_profile([{"label": "Name", "value": "Jon Doe"}])
    store.save_manual({"Name": "Jon Doe"})

    store.clear_resume()

    assert store.current_resume() is None
    assert store.load_profile() is None
    assert store.load_manual() == {}
    assert not any(local_data.iterdir())


def test_memory_preserves_question_and_does_not_rewrite_identical_answer(local_data: Path) -> None:
    assert store.remember("Will you need sponsorship?", "No", "radio") is True
    first = store.load_answers()
    key = "will you need sponsorship"
    before = store.ANSWERS.stat().st_mtime_ns

    assert store.remember("Will you need sponsorship?", "No", "radio") is False

    saved = store.load_answers()[key]
    assert saved["q"] == "Will you need sponsorship?"
    assert saved["a"] == "No"
    assert saved["n"] == 1
    assert saved["wordings"] == ["Will you need sponsorship?"]
    assert store.ANSWERS.stat().st_mtime_ns == before
    assert saved == first[key]


def test_memory_tracks_rewording_and_edit(local_data: Path) -> None:
    store.remember("Need sponsorship?", "No", "radio")
    assert store.remember("Need sponsorship", "No", "radio") is True

    entry = store.update_answer("need sponsorship", answer="No, now or in the future.", question="Visa sponsorship")

    assert entry is not None
    assert entry["key"] == "visa sponsorship"
    assert entry["a"] == "No, now or in the future."
    assert entry["n"] == 2  # edits do not count as another form use
    assert entry["q"] == "Visa sponsorship"
    assert "Need sponsorship?" in entry["wordings"]
    assert "Need sponsorship" in entry["wordings"]


def test_erase_all_removes_personal_data_but_not_settings_until_requested(local_data: Path) -> None:
    store.save_text("Jon Doe\nSoftware engineer with enough text for a resume.")
    store.save_profile([{"label": "Name", "value": "Jon Doe"}])
    store.save_manual({"Name": "Jon Doe"})
    store.remember("Are you authorized to work?", "Yes")
    settings.update({"appearance": {"font_size": 17}})

    store.clear_all()

    assert store.current_resume() is None
    assert store.load_answers() == {}
    assert store.load_profile() is None
    assert settings.load()["appearance"]["font_size"] == 17


def test_settings_drops_legacy_theme_overrides_and_writes_private_file(local_data: Path) -> None:
    local_data.mkdir()
    settings.PATH.write_text(json.dumps({"appearance": {"follow_omarchy": False, "accent": "#123456", "font_size": 16}}))

    loaded = settings.load()
    updated = settings.update({"appearance": {"font": "sans", "ignored": "value"}})

    assert loaded["appearance"] == {"font_size": 16, "font": "mono"}
    assert updated["appearance"] == {"font_size": 16, "font": "sans"}
    assert json.loads(settings.PATH.read_text())["appearance"] == updated["appearance"]
    assert os.stat(settings.PATH).st_mode & 0o777 == 0o600


def test_theme_uses_applied_palette_and_falls_back_for_missing_roles(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    applied = tmp_path / "current" / "colors.toml"
    name = tmp_path / "current" / "theme.name"
    applied.parent.mkdir(parents=True)
    applied.write_text('mode = "light"\nbackground = "#ffffff"\nforeground = "#111111"\naccent = "#336699"\n')
    name.write_text("demo-theme\n")
    monkeypatch.setattr(theme, "APPLIED", applied)
    monkeypatch.setattr(theme, "APPLIED_NAME", name)

    loaded = theme.load()

    assert loaded["name"] == "Demo Theme"
    assert loaded["revision"]
    assert loaded["colors"]["mode"] == "light"
    assert loaded["colors"]["background"] == "#ffffff"
    assert loaded["colors"]["accent"] == "#336699"
    assert loaded["colors"]["red"] == theme.FALLBACK["red"]


def test_theme_rejects_invalid_mode(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    applied = tmp_path / "colors.toml"
    applied.write_text('mode = "sepia"\nbackground = "#ffffff"\nforeground = "#111111"\n')
    monkeypatch.setattr(theme, "APPLIED", applied)
    monkeypatch.setattr(theme, "APPLIED_NAME", tmp_path / "missing-name")
    monkeypatch.setattr(theme, "current_name", lambda: "")

    assert theme.load()["colors"]["mode"] == "dark"

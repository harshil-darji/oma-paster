"""cua-s1 local option scorer — batch-score form fields against document entities."""

from __future__ import annotations

import re
import threading
import time
from pathlib import Path

import torch
from cua_s1.model import ChoiceExample, load_checkpoint, select_device
from cua_s1.schema import Decision, Element, Entity, decode, render_context, render_options
from huggingface_hub import hf_hub_download

GITHUB_FIELD = re.compile(r"\bgithub\b", re.I)
X_FIELD = re.compile(r"\b(x|twitter)\b", re.I)


class CuaS1Backend:
    """Planning backend compatible with cua_s1.planner.Planner."""

    def __init__(
        self,
        repo_id: str = "cua-ai/cua-s1-forms",
        device: str = "cpu",
        cache_dir: str | Path | None = None,
    ) -> None:
        self.repo_id = repo_id
        self.device_name = device
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self._model = None
        self._collator = None
        self._device: torch.device | None = None
        self._lock = threading.Lock()

    def ensure_loaded(self) -> None:
        with self._lock:
            if self._model is not None:
                return
            weights = Path(
                hf_hub_download(
                    self.repo_id,
                    "cua-s1-forms.safetensors",
                    cache_dir=str(self.cache_dir) if self.cache_dir else None,
                )
            )
            hf_hub_download(
                self.repo_id,
                "cua-s1-forms.json",
                local_dir=str(weights.parent),
                cache_dir=str(self.cache_dir) if self.cache_dir else None,
            )
            device = select_device(self.device_name)
            model, collator, _config = load_checkpoint(weights, device)
            self._model = model
            self._collator = collator
            self._device = device

    def plan(
        self,
        form_title: str,
        elements: list[Element],
        entities: list[Entity],
    ) -> list[Decision]:
        self.ensure_loaded()
        assert self._model is not None and self._collator is not None and self._device is not None

        if not elements:
            return []
        if not entities:
            return [
                Decision(element=element, action="skip", entity_index=None, probability=1.0)
                for element in elements
            ]

        # Score only against cua-s1-familiar labels; keep X/GitHub for overlays.
        score_entities = [
            entity
            for entity in entities
            if entity.label not in {"X", "GitHub", "Date of birth"}
        ] or list(entities)

        options = render_options(score_entities)
        examples = [
            ChoiceExample(
                context=render_context(form_title, element),
                options=tuple(options),
                label=0,
            )
            for element in elements
        ]
        batch = self._collator(examples)
        batch = {key: value.to(self._device) for key, value in batch.items()}
        with torch.inference_mode():
            logits = self._model(batch)
            probs = torch.softmax(logits, dim=-1)

        decisions: list[Decision] = []
        for index, element in enumerate(elements):
            distribution = probs[index, : len(options)].detach().cpu().tolist()
            choice = int(probs[index, : len(options)].argmax().item())
            action, entity_index = decode(choice, score_entities)
            if element.value.strip() and action == "fill":
                action, entity_index = "skip", None
            # Remap entity index into the full entity list.
            if action == "fill" and entity_index is not None:
                chosen = score_entities[entity_index]
                entity_index = next(
                    (
                        i
                        for i, entity in enumerate(entities)
                        if entity.label == chosen.label and entity.value == chosen.value
                    ),
                    None,
                )
                if entity_index is None:
                    action = "skip"
            decisions.append(
                Decision(
                    element=element,
                    action=action,
                    entity_index=entity_index,
                    probability=float(distribution[choice]),
                    distribution=distribution,
                )
            )
        return decisions

    def fill_map(
        self,
        form_title: str,
        fields: list[dict],
        entities: list[Entity],
        *,
        min_confidence: float = 0.35,
    ) -> dict:
        """Score fields and return a DOM fill map for the web demo."""

        started = time.perf_counter()
        self.ensure_loaded()
        loaded_at = time.perf_counter()

        elements = [
            Element(
                role=str(field.get("role") or "Edit"),
                label=str(field["label"]),
                value=str(field.get("value") or ""),
                index=index,
                element_token=str(field["id"]),
            )
            for index, field in enumerate(fields)
        ]
        decisions = self.plan(form_title, elements, entities)
        planned_at = time.perf_counter()

        fills: dict[str, str] = {}
        details = []
        for decision in decisions:
            field_id = decision.element.element_token or str(decision.element.index)
            entity = (
                entities[decision.entity_index]
                if decision.entity_index is not None
                else None
            )
            entry = {
                "field_id": field_id,
                "label": decision.element.label,
                "action": decision.action,
                "confidence": round(decision.probability, 4),
                "entity_label": entity.label if entity else None,
                "value": entity.value if entity else None,
                "source": "cua-s1",
            }
            details.append(entry)
            if (
                decision.action == "fill"
                and entity is not None
                and decision.probability >= min_confidence
            ):
                fills[field_id] = entity.value

        _apply_social_overlay(fields, entities, fills, details)

        finished = time.perf_counter()
        return {
            "fills": fills,
            "decisions": details,
            "timings_ms": {
                "load_or_warmup": round((loaded_at - started) * 1000, 1),
                "score": round((planned_at - loaded_at) * 1000, 1),
                "total": round((finished - started) * 1000, 1),
            },
        }


def _apply_social_overlay(
    fields: list[dict],
    entities: list[Entity],
    fills: dict[str, str],
    details: list[dict],
) -> None:
    """Fill X/GitHub fields cua-s1 was never trained on."""

    by_label = {entity.label: entity.value for entity in entities}
    github = by_label.get("GitHub")
    x_handle = by_label.get("X")
    if not github and not x_handle:
        return

    detail_by_id = {item["field_id"]: item for item in details}
    for field in fields:
        field_id = str(field["id"])
        if field_id in fills:
            continue
        label = str(field["label"])
        if github and GITHUB_FIELD.search(label):
            fills[field_id] = github
            if field_id in detail_by_id:
                detail_by_id[field_id].update(
                    {
                        "action": "fill",
                        "value": github,
                        "entity_label": "GitHub",
                        "source": "social-overlay",
                        "confidence": 1.0,
                    }
                )
        elif x_handle and X_FIELD.search(label):
            fills[field_id] = x_handle
            if field_id in detail_by_id:
                detail_by_id[field_id].update(
                    {
                        "action": "fill",
                        "value": x_handle,
                        "entity_label": "X",
                        "source": "social-overlay",
                        "confidence": 1.0,
                    }
                )

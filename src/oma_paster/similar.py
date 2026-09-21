"""Match a reworded form question to one you've answered before (small local embedding model)."""

from __future__ import annotations

import threading

MODEL = "sentence-transformers/all-MiniLM-L6-v2"
THRESHOLD = 0.65  # cosine; fuzzy matches are always confirmed by the user, so lean toward recall


class Matcher:
    def __init__(self, model_id: str = MODEL) -> None:
        self.model_id = model_id
        self._tok = None
        self._model = None
        self._lock = threading.Lock()
        self._cache: dict[str, object] = {}
        self.failed = False
        self.error = ""

    def _load(self) -> bool:
        with self._lock:
            if self._model is not None:
                return True
            if self.failed:
                return False
            try:
                from transformers import AutoModel, AutoTokenizer

                self._tok = AutoTokenizer.from_pretrained(self.model_id)
                self._model = AutoModel.from_pretrained(self.model_id).eval()
                return True
            except Exception as exc:  # noqa: BLE001 - offline / missing download: fall back to exact matches
                self.failed = True
                self.error = str(exc).splitlines()[0][:200]
                return False

    def ensure_loaded(self) -> None:
        if not self._load():
            raise RuntimeError(self.error or "could not load")

    def _embed(self, texts: list[str]):
        import torch

        batch = self._tok(texts, padding=True, truncation=True, max_length=64, return_tensors="pt")
        with torch.no_grad():
            out = self._model(**batch).last_hidden_state
        mask = batch["attention_mask"].unsqueeze(-1)
        vec = (out * mask).sum(1) / mask.sum(1).clamp(min=1)
        return torch.nn.functional.normalize(vec, dim=1)

    def best(self, label: str, answers: dict[str, dict]) -> tuple[dict, float] | None:
        """Most similar saved question to `label`, if it clears the threshold."""
        if not label.strip() or not answers or not self._load():
            return None
        import torch

        missing = [k for k in answers if k not in self._cache]
        if missing:
            for k, v in zip(missing, self._embed([answers[k]["q"] for k in missing])):
                self._cache[k] = v
        keys = list(answers)
        matrix = torch.stack([self._cache[k] for k in keys])
        scores = matrix @ self._embed([label])[0]
        idx = int(scores.argmax())
        score = float(scores[idx])
        return (answers[keys[idx]], score) if score >= THRESHOLD else None

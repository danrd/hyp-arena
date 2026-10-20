"""Context flags for evidence records: disease models, progeroid and short-lived strains, special diets
(configs/disease_models.yaml). Which strain a study used is in the text; what the strain means is a lookup,
not a judgement, so code flags it instead of the model. A flag lowers trust and is shown; it does not change a
status by itself (card spec 7). The evidence profile notes when the effect level rests on flagged records only."""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

import yaml

TABLE = Path(__file__).resolve().parents[2] / "configs" / "disease_models.yaml"
FLAG = {"disease_model": "disease_model", "progeroid": "short_lived_controls",
        "accelerated_aging": "short_lived_controls", "special_diet": "special_diet"}


@lru_cache(maxsize=1)
def _models() -> list[tuple[re.Pattern, dict]]:
    data = yaml.safe_load(TABLE.read_text(encoding="utf-8"))
    return [(re.compile(rf"(?<![\w-])(?:{m['pattern']})(?![\w-])", re.I), m) for m in data["models"]]


def find(text: str) -> list[dict]:
    """Models named in a text (abstract, DrugAge strain), each once."""
    out, seen = [], set()
    for pat, m in _models():
        if m["name"] not in seen and pat.search(text or ""):
            seen.add(m["name"])
            out.append(m)
    return out


def find_strain(strain: str) -> list[dict]:
    """Models a curated strain name (DrugAge's strain field) stands for."""
    s = (strain or "").strip().lower()
    return [m for _, m in _models() if s and (s in {x.lower() for x in m.get("strains", [])})] or (find(strain) if s else [])


def flag(record, text: str = "", strain: str = "") -> None:
    """Add the flags and a note for the models named in `text` (an abstract) or by `strain` to a record."""
    models = find(text) if text else []
    models += [m for m in find_strain(strain) if m not in models]
    for m in models:
        f = FLAG[m["category"]]
        if f not in record.flags:
            record.flags.append(f)
    if models:
        note = "context: " + "; ".join(f"{m['name']} ({m['note']})" for m in models)
        record.notes = f"{record.notes}; {note}" if record.notes else note


CONTEXT_FLAGS = set(FLAG.values())

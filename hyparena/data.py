"""Load externally produced hypotheses (the ChatGPT dataset) as graph hypotheses with known provenance."""
from __future__ import annotations

import json
from pathlib import Path

from hyparena.state import Hypothesis, Provenance

#: Field order and headings used to rebuild the free text of an imported hypothesis.
FIELDS = (("claim", "Гипотеза"), ("rationale", "Обоснование"), ("known", "Что уже известно"), ("experiment", "Решающий эксперимент"),
          ("prediction", "Специфическое предсказание"), ("falsification", "Что опровергнет гипотезу"),
          ("intervention", "Потенциальное вмешательство"))
#: The same headings for datasets in English (`source.options.lang: en`).
HEADINGS_EN = {"claim": "Hypothesis", "rationale": "Rationale", "known": "What is known", "experiment": "Decisive experiment",
               "prediction": "Specific prediction", "falsification": "What would refute it",
               "intervention": "Potential intervention"}


def dataset_options(path: str | Path) -> dict:
    """Run options a dataset asks for, e.g. {"dedup": false} for templated pools whose items differ only
    in a name (word-overlap deduplication would merge distinct interventions)."""
    return (json.loads(Path(path).read_text(encoding="utf-8")).get("source") or {}).get("options", {})


def load_imported(path: str | Path, limit: int | None = None) -> list[Hypothesis]:
    """Hypotheses from the dataset JSON. The writer's family and model come from the dataset's `source`
    (needed by the judge independence rule). With `limit`, an evenly spaced sample is taken so that
    early and late hypotheses of the dialogue are both represented."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    source = data.get("source") or {}
    english = (source.get("options") or {}).get("lang") == "en"
    items = data["hypotheses"]
    if limit and limit < len(items):
        step = len(items) / limit
        items = [items[int(i * step)] for i in range(limit)]
    prov = Provenance(family=source.get("family", "unknown"), model_version=source.get("model", "unknown"),
                      role="imported", strategy=source.get("strategy", "chatgpt-dialogue"))
    out = []
    for it in items:
        body = "\n\n".join(f"{HEADINGS_EN[key] if english else title}: {it[key]}" for key, title in FIELDS if it.get(key))
        out.append(Hypothesis(id=f"imp{it['id']:03d}", text=f"{it['title']}\n\n{body}", provenance=prov))
    return out

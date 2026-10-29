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


AGING = {"progeroid", "accelerated_aging"}
ALIASES = {"als": ("als", "amyotrophic lateral sclerosis", "motor neuron disease"),
           "huntington": ("huntington",), "alzheimer": ("alzheimer", "amyloid pathology"),
           "muscular dystrophy": ("muscular dystrophy", "dystrophy"),
           "lupus": ("lupus",), "cancer": ("cancer", "tumour", "tumor", "leukaemia", "leukemia", "carcinoma", "mammary"),
           "diabetes": ("diabet",), "atherosclerosis": ("atherosclerosis",), "hypertension": ("hypertens",)}


def disease_name(m: dict) -> str:
    """The disease a table entry stands for: its `disease` field, else the first part of its note."""
    return (m.get("disease") or (m.get("note") or "").split(",")[0]).strip()


def disease_key(text: str) -> str:
    """A disease name as a comparable key: a known disease (ALS, amyotrophic lateral sclerosis) or the plain words."""
    t = re.sub(r"[^\w ]+", " ", (text or "").lower())
    t = re.sub(r"\s+", " ", t).strip()
    for key, names in ALIASES.items():
        if any(re.search(rf"\b{re.escape(n)}", t) if n == "als" else n in t for n in names):
            return key
    return t


def disease_in(text: str) -> str:
    """A known disease named in a text (a claim's population or qualifiers), or an empty string."""
    t = (text or "").lower()
    for key, names in ALIASES.items():
        if any(re.search(r"\bals\b", t) if n == "als" else n in t for n in names):
            return key
    return ""


def same_disease(a: str, b: str) -> bool:
    ka, kb = disease_key(a), disease_key(b)
    return bool(ka) and bool(kb) and (ka == kb or ka in kb or kb in ka)


def _sentence(text: str, start: int, end: int) -> str:
    left = max(text.rfind(". ", 0, start), text.rfind("\n", 0, start))
    right = min([i for i in (text.find(". ", end), text.find("\n", end)) if i >= 0] or [len(text)])
    return re.sub(r"\s+", " ", text[left + 1 if left >= 0 else 0:right + 1]).strip()[:300]


def flag(record, text: str = "", strain: str = "") -> None:
    """Add the flags and a note for the models named in `text` (an abstract) or by `strain` to a record. A disease
    model is also recorded as `model_type`, `disease` and `disease_evidence` (the sentence that names it, or the
    curated strain field): the rules read these fields, never the bare flag, and a model without a disease name
    and a place where it is named is not a disease model. Accelerated-ageing models get `model_type: aging_model`."""
    found = []                                            # (table entry, where it is named)
    for pat, m in _models():
        hit = pat.search(text or "")
        if hit and all(m["name"] != x["name"] for x, _ in found):
            found.append((m, _sentence(text, hit.start(), hit.end())))
    for m in find_strain(strain):
        if all(m["name"] != x["name"] for x, _ in found):
            found.append((m, f"curated strain: {strain}"))
    for m, where in found:
        f = FLAG[m["category"]]
        if f not in record.flags:
            record.flags.append(f)
    disease = next(((m, w) for m, w in found if m["category"] == "disease_model" and disease_name(m) and w), None)
    aging = next(((m, w) for m, w in found if m["category"] in AGING and w), None)
    if disease and not record.model_type:
        record.model_type, record.disease, record.disease_evidence = "disease_model", disease_name(disease[0]), disease[1]
    elif aging and not record.model_type:
        record.model_type, record.disease, record.disease_evidence = "aging_model", aging[0]["name"], aging[1]
        if "aging_model" not in record.flags:
            record.flags.append("aging_model")
    if found:
        note = "context: " + "; ".join(f"{m['name']} ({m['note']})" for m, _ in found)
        if note not in record.notes:
            record.notes = f"{record.notes}; {note}" if record.notes else note


GENOTYPE = re.compile(
    r"\b(?:mutants?|knock-?outs?|knock-?downs?|null\s+(?:alleles?|mutants?)|loss[- ]of[- ]function|transgenic|hypomorph\w*)\b"
    r"|\b[a-z]{3,4}-\d+\s*\([a-z]{1,3}\d+\)"          # worm alleles: daf-16(mu86), daf-2(e1370)
    r"|[-−–]/[-−–]|\+/[-−–]",                              # mouse genotypes: -/-, +/-
    re.I)


def genotype_in(text: str) -> str:
    """The words of a text that name a mutant or engineered genotype ("daf-16(mu86)", "knockout", "-/-"), or an empty string. Used by the offline
    evaluation of a mutant-context rule (scripts/extraction_fixes_eval.py); the rule itself was not adopted (docs/rules-method.md, L1.17)."""
    m = GENOTYPE.search(text or "")
    return m.group(0) if m else ""


CONTEXT_FLAGS = {"special_diet"}                      # flags that still only qualify an effect level (disease and ageing models do not enter it)

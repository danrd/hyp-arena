"""Extraction against the DrugAge gold, at the level of cells (compound, species, sex) with a direction.

    python -m scripts.extraction_compare kg  [--kg-dir /home/user/longevity-kg]     # rows extracted for the graph vs the DrugAge rows

The article texts and the extracted rows stay in the private longevity-kg repository (publishers' texts); this script only reads them
from $KG_DIR (default /home/user/longevity-kg) and prints numbers. Nothing from the corpus is written into this repository.

Cell. One result for a compound in a species for one sex group; the direction is `increase`, `decrease` or `no_effect`.
Gold (DrugAge): one cell per row, sex Male / Female, any other value (Unknown, Pooled, Both) matches both; direction from the change of the
average lifespan (significant and positive: increase, significant and negative: decrease, not significant: no_effect), the change of the maximum
lifespan if the average is missing. Prediction: a row of the graph (outcome lifespan, quote_role finding) or a record of a verifier family
(endpoint lifespan, quote_role finding) with the effect direction.
Measures (criterion L1.17 in specs/validation-criteria.yaml): found = share of gold cells with a predicted cell for the same compound, species and a
compatible sex; correct = share with the same direction too; precision = share of predicted cells that match a gold cell (a lower bound:
DrugAge may omit a result the article reports).
"""
from __future__ import annotations

import argparse
import json
import os
import re
from collections import defaultdict
from pathlib import Path

DEFAULT_KG = os.environ.get("KG_DIR", "/home/user/longevity-kg")
SEX = {"male": "male", "female": "female"}
SPECIES = {"mus musculus": "mouse", "mouse": "mouse", "mice": "mouse", "rattus norvegicus": "rat", "rat": "rat",
           "caenorhabditis elegans": "worm", "worm": "worm", "c. elegans": "worm",
           "drosophila melanogaster": "fly", "fly": "fly", "drosophila": "fly",
           "saccharomyces cerevisiae": "yeast", "yeast": "yeast"}


SPELLING = (("aluminium", "aluminum"), ("sulphate", "sulfate"), ("sulphur", "sulfur"), ("oestr", "estr"))
GENERIC = {"extract", "extracts", "derived", "polypeptide", "polypeptides", "factor", "factors", "fraction", "preparation", "and", "the", "of"}


def _key(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())


def _tokens(s: str) -> set[str]:
    """Distinctive words of a compound name: spelling variants unified, generic words and short abbreviations dropped."""
    t = (s or "").lower()
    for a, b in SPELLING:
        t = t.replace(a, b)
    return {w for w in re.findall(r"[a-z0-9]+", t) if w not in GENERIC and len(w) > 3}


SPECIES_WORDS = (("mouse", r"\b(mouse|mice|mus|murine)\b"), ("rat", r"\b(rat|rats|rattus)\b"), ("worm", r"(elegans|nematode|\bworms?\b)"),
                 ("fly", r"(drosophila|fruit fl|\bfl(?:y|ies)\b)"), ("yeast", r"(yeast|saccharomyces|cerevisiae)"))


def species_key(s: str) -> str:
    """Species group of a free-text organism label: the exact names first, then words ("f344 rats" and "wistar-unilever rats" are rats)."""
    t = (s or "").strip().lower()
    if t in SPECIES:
        return SPECIES[t]
    for name, pattern in SPECIES_WORDS:
        if re.search(pattern, t):
            return name
    return t


def sex_key(s: str) -> str:
    return SEX.get((s or "").strip().lower(), "any")


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def gold_cells(rows: list[dict]) -> list[dict]:
    out, seen = [], set()
    for r in rows:
        for pct, sig in ((r.get("avg_lifespan_change_percent"), r.get("avg_lifespan_significance")),
                         (r.get("max_lifespan_change_percent"), r.get("max_lifespan_significance"))):
            p = _num(pct)
            if p is None or (sig or "").strip() not in ("S", "NS"):
                continue
            d = ("increase" if p > 0 else "decrease" if p < 0 else "no_effect") if sig.strip() == "S" else "no_effect"
            cell = {"compound": r["compound_name"], "species": species_key(r["species"]), "sex": sex_key(r.get("gender", "")), "direction": d}
            if (t := tuple(cell.values())) not in seen:
                seen.add(t)
                out.append(cell)
            break                                           # the average decides; the maximum only when the average is missing
    return out


def kg_cells(rows: list[dict]) -> list[dict]:
    """Cells from the observation rows of the graph (lifespan findings only)."""
    out, seen = [], set()
    for r in rows:
        if "organism" not in r or r["outcome"]["endpoint"] != "lifespan" or r["provenance"]["quote_role"] != "finding":
            continue
        d = r["result"]["direction"]
        if d not in ("increase", "decrease", "no_effect"):
            continue
        if r["result"].get("significance") == "NS":
            d = "no_effect"                                  # the gold calls a change that is not significant no effect
        cell = {"compound": r["intervention"]["label"], "species": species_key(r["organism"]["species"]),
                "sex": sex_key(r["organism"]["sex"]), "direction": d}
        if (t := tuple(cell.values())) not in seen:
            seen.add(t)
            out.append(cell)
    return out


def record_cells(records: list[dict], compound: str) -> list[dict]:
    """Cells from the records of a verifier family (the fields of `verify_claim/v5` replies); the compound is the one of the claim."""
    out, seen = [], set()
    for r in records:
        if r.get("endpoint") != "lifespan" or r.get("quote_role") != "finding" or r.get("effect") not in ("increase", "decrease", "no_effect"):
            continue
        sex = r.get("sexes") or [r.get("sex")]
        sex = sex[0] if isinstance(sex, list) and len(sex) == 1 else "any"
        cell = {"compound": compound, "species": species_key(r.get("species", "")), "sex": sex_key(sex), "direction": r["effect"]}
        if (t := tuple(cell.values())) not in seen:
            seen.add(t)
            out.append(cell)
    return out


def _same_compound(a: str, b: str) -> bool:
    """Names are compared as words: at least half of the distinctive words of the shorter name occur in the other, or one key contains the other."""
    ta, tb = _tokens(a), _tokens(b)
    if ta and tb and len(ta & tb) / min(len(ta), len(tb)) >= 0.5:
        return True
    ka, kb = _key(a), _key(b)
    return ka == kb or (len(ka) >= 5 and len(kb) >= 5 and (ka in kb or kb in ka))


def _match(g: dict, p: dict) -> bool:
    return (_same_compound(g["compound"], p["compound"]) and g["species"] == p["species"]
            and (g["sex"] == "any" or p["sex"] == "any" or g["sex"] == p["sex"]))


def compare(gold: list[dict], pred: list[dict]) -> dict:
    found = sum(any(_match(g, p) for p in pred) for g in gold)
    correct = sum(any(_match(g, p) and g["direction"] == p["direction"] for p in pred) for g in gold)
    matched = sum(any(_match(g, p) for g in gold) for p in pred)
    right = sum(any(_match(g, p) and g["direction"] == p["direction"] for g in gold) for p in pred)
    return {"gold_cells": len(gold), "pred_cells": len(pred), "found": found, "correct": correct, "pred_matched": matched, "pred_right": right}


def totals(parts: list[dict]) -> dict:
    s = {k: sum(p[k] for p in parts) for k in ("gold_cells", "pred_cells", "found", "correct", "pred_matched", "pred_right")}
    s["found_rate"] = round(s["found"] / s["gold_cells"], 3) if s["gold_cells"] else None
    s["correct_rate"] = round(s["correct"] / s["gold_cells"], 3) if s["gold_cells"] else None
    s["precision"] = round(s["pred_matched"] / s["pred_cells"], 3) if s["pred_cells"] else None
    s["direction_given_found"] = round(s["correct"] / s["found"], 3) if s["found"] else None
    return s


def load_gold(kg_dir: str) -> dict[str, list[dict]]:
    by = defaultdict(list)
    for line in Path(kg_dir, "gold", "drugage_by_pmid.jsonl").read_text().splitlines():
        if line.strip():
            r = json.loads(line)
            by[str(r["pmid"])].append(r)
    return by


def load_kg_rows(kg_dir: str) -> dict[str, list[dict]]:
    out = {}
    for f in sorted(Path(kg_dir, "extracted").glob("*.jsonl")):
        out[f.stem] = [json.loads(x) for x in f.read_text().splitlines() if x.strip()]
    return out


def kg_report(kg_dir: str) -> dict:
    gold, rows = load_gold(kg_dir), load_kg_rows(kg_dir)
    per = {}
    for pmid, rs in rows.items():
        if pmid in gold:
            per[pmid] = compare(gold_cells(gold[pmid]), kg_cells(rs))
    return {"papers": len(per), "total": totals(list(per.values())), "per_paper": per}


TEMPLATE_CARD = "runs/stage5/l1_8/O1.json"             # any saved card of the pipeline: the structure the verifier template reads
STRATA = {"mouse": 25, "worm": 15, "fly": 15, "rat": 5}
TEST_FILE = Path("data/validation/extraction/test_pmids.json")


def select_test(kg_dir: str) -> dict:
    """The frozen test subset (PMIDs only): papers of the graph corpus with gold rows, at most 3 compounds, an abstract of at least 500
    characters and not a review; stratified by species, ordered by a hash of the PMID. `corpus_sha256` hashes the texts' own hashes, so a change
    of the corpus text is noticed."""
    import hashlib
    gold = load_gold(kg_dir)
    chosen = {sp: [] for sp in STRATA}
    for pmid in sorted(gold, key=lambda p: hashlib.sha1(p.encode()).hexdigest()):
        f = Path(kg_dir, "corpus", f"{pmid}.md")
        if not f.exists():
            continue
        text = f.read_text(encoding="utf-8")
        head = text.split("---")[1] if text.startswith("---") else ""
        if "Review" in head or len(text.split("## Abstract")[-1].strip()) < 500:
            continue
        species = {species_key(r["species"]) for r in gold[pmid]}
        compounds = {_key(r["compound_name"]) for r in gold[pmid]}
        if len(species) != 1 or len(compounds) > 3:
            continue
        sp = next(iter(species))
        if sp in chosen and len(chosen[sp]) < STRATA[sp]:
            chosen[sp].append(pmid)
    pmids = [p for sp in STRATA for p in chosen[sp]]
    hashes = []
    for p in pmids:
        m = re.search(r"text_sha256:\s*\"?([0-9a-f]{64})", Path(kg_dir, "corpus", f"{p}.md").read_text(encoding="utf-8"))
        hashes.append(m.group(1) if m else "")
    return {"strata": {sp: len(v) for sp, v in chosen.items()}, "pmids": pmids,
            "corpus_sha256": hashlib.sha256("".join(hashes).encode()).hexdigest()}


SPECIES_LATIN = {"mouse": "Mus musculus", "rat": "Rattus norvegicus", "worm": "Caenorhabditis elegans", "fly": "Drosophila melanogaster"}


def _claim_card(compound: str, species: str) -> dict:
    """A card by code for the claim "compound extends the lifespan of species": the structure of a saved card with the compound and the species replaced."""
    import copy
    base = next(x["card"] for x in json.loads(Path(TEMPLATE_CARD).read_text())["items"] if x.get("card"))
    c = copy.deepcopy(base)
    k = next(x for x in c["claims"] if x["role"] == "outcome")
    c["claims"] = [k]
    c["edges"] = []
    for key in [key for key in c if "alternatives" in key]:
        c[key] = []
    latin = SPECIES_LATIN.get(species, species)
    c["claim_plain"] = f"{compound} extends the lifespan of {latin}."
    c["pico"]["intervention"] = [{"type": "compound", "label": compound, "id": None, "regimen": "unknown", "route": "unknown"}]
    c["pico"]["population"] = {"taxon": None, "label": latin, "strain": "unknown", "sex": "unknown", "age_at_start": "unknown"}
    k["id"], k["relation"] = "c1", "extends_lifespan_in"
    k["subject"] = {"label": compound, "id": None, "hallmark": None}
    k["object"] = {"label": latin, "id": None, "hallmark": None}
    k["qualifiers"] = {"species": latin}
    k["source_span"] = f"{compound} extends the lifespan of {latin}"
    return c


def extract(client, family: str, kg_dir: str, pmid: str, compound: str, species: str) -> list[dict]:
    """Records of one verifier family for the claim about `compound` from the one abstract of `pmid` (the prompt of `verify_claim/v5`, no search)."""
    from hyparena.card import verifier as v
    from hyparena.card.llm import ask
    from hyparena.card.models import HypothesisCard
    from hyparena.card.rules import claim_endpoint
    text = Path(kg_dir, "corpus", f"{pmid}.md").read_text(encoding="utf-8")
    title = re.search(r"## Title\n(.*?)\n\n## Abstract", text, re.S).group(1).strip()
    abstract = text.split("## Abstract", 1)[1].strip()
    year = (re.search(r"year:\s*\"?(\d{4})", text) or [None, ""])[1]
    abstracts = {pmid: {"title": title, "abstract": abstract, "year": year}}
    card = HypothesisCard.model_validate(_claim_card(compound, species))
    claim = card.claims[0]
    variables = {"claim": claim, "negated": False, "alternative": False, "human_healthspan": False, "contrast": "",
                 "qualifiers": ", ".join(f"{k}: {x}" for k, x in claim.qualifiers.items()), "endpoint": claim_endpoint(claim), "claim_plain": card.claim_plain,
                 "population": ", ".join(f"{k} {x}" for k, x in card.pico.population.model_dump().items() if x and x != "unknown") or "unknown",
                 "intervention": f"{compound} (regimen unknown)", "comparator": card.pico.comparator.label,
                 "abstracts": [{"pmid": pmid, "year": year, "title": title, "abstract": abstract, "review": False}]}
    value, _ = ask(client, role="verify_claim", family=family, template=v.TEMPLATE[0], version=v.TEMPLATE[1], variables=variables,
                   validate=lambda x: v._validate(x, abstracts), rounds=2, avoid=frozenset(), log=None, parse=v.parse_records)
    return (value or {}).get("records") or []


def run_families(kg_dir: str, out: str, families: list[str], max_calls: int = 400, repeat: str | None = None) -> None:
    """Every (paper, compound) of the frozen test subset for every family; the raw records are saved to `out`."""
    from concurrent.futures import ThreadPoolExecutor

    from hyparena.card.pipeline import _client
    gold = load_gold(kg_dir)
    pmids = json.loads(TEST_FILE.read_text())["pmids"]
    pairs = []
    for p in pmids:
        seen = {}
        for r in gold[p]:
            seen.setdefault(_key(r["compound_name"]), (r["compound_name"], species_key(r["species"])))
        pairs += [(p, c, sp) for c, sp in seen.values()]
    Path(out).mkdir(parents=True, exist_ok=True)
    for fam in families:
        client, _ = _client(f"configs/v2-agree-{fam}.yaml", False, max_calls)
        with ThreadPoolExecutor(4) as pool:
            recs = list(pool.map(lambda t: extract(client, fam, kg_dir, *t), pairs))
        name = f"{fam}{'_' + repeat if repeat else ''}.json"
        Path(out, name).write_text(json.dumps([{"pmid": p, "compound": c, "species": sp, "records": r} for (p, c, sp), r in zip(pairs, recs)], ensure_ascii=False))
        print(fam, "pairs", len(pairs), "calls", client.calls, flush=True)


def families_report(out: str, kg_dir: str) -> dict:
    gold = load_gold(kg_dir)
    res = {}
    for f in sorted(Path(out).glob("*.json")):
        by = defaultdict(list)
        data = json.loads(f.read_text())
        parts = []
        for item in data:
            pred = record_cells(item["records"], item["compound"])
            g = [c for c in gold_cells(gold[item["pmid"]]) if _same_compound(c["compound"], item["compound"]) and c["species"] == item["species"]]
            parts.append(compare(g, pred))
        res[f.stem] = totals(parts)
    return res


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    rn = sub.add_parser("run", help="paid: the verifier families on the frozen test subset")
    rn.add_argument("--kg-dir", default=DEFAULT_KG)
    rn.add_argument("--out", required=True)
    rn.add_argument("--families", default="deepseek,google,zhipu")
    rn.add_argument("--repeat", default=None, help="suffix of the files of a repeat run (noise of the same family)")
    rp = sub.add_parser("report", help="the measures of every saved family file")
    rp.add_argument("--kg-dir", default=DEFAULT_KG)
    rp.add_argument("--out", required=True)
    k = sub.add_parser("kg")
    k.add_argument("--kg-dir", default=DEFAULT_KG)
    sl = sub.add_parser("select", help="write the frozen test subset (PMIDs only)")
    sl.add_argument("--kg-dir", default=DEFAULT_KG)
    a = ap.parse_args()
    if a.cmd == "run":
        run_families(a.kg_dir, a.out, a.families.split(","), repeat=a.repeat)
    elif a.cmd == "report":
        print(json.dumps(families_report(a.out, a.kg_dir), indent=1))
    elif a.cmd == "select":
        d = select_test(a.kg_dir)
        TEST_FILE.write_text(json.dumps(d, indent=1))
        print(d["strata"], len(d["pmids"]), d["corpus_sha256"][:16])
    else:
        print(json.dumps(kg_report(a.kg_dir), indent=1))


if __name__ == "__main__":
    main()

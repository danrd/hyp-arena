"""L3.3 and L3.9 on the clean ITP + CITP pool (T = 2024-12-31) without an LLM verifier: no model reads the pool.

    python -m scripts.clean_backtest cards --pool data/backtest/outcomes_2024-12-31.json --out runs/clean/cards.json
    python -m scripts.clean_backtest run --pool data/backtest/outcomes_2024-12-31.json --spec specs/clean-2024-12-31.yaml \\
        --out runs/clean/clean_2024.json
    python -m scripts.clean_backtest evaluate --labels data/backtest/outcomes_2024-12-31_labels.json --run runs/clean/clean_2024.json

Policy (user decision 2026-10-29, Working_Notes 7j point 1): the card of each hypothesis is written by code from the hypothesis text
(compound, species, strain, start age, dose wording); nothing of the labels file reaches `cards` or `run`. Evidence comes only from
structured sources as of T: curated DrugAge records of papers public by T, ChEMBL first approval year and ClinicalTrials.gov start
dates (path_to_human). PubMed search and every model are off. Besides the outcome claim, the verifier layer adds one probe per other
DrugAge species (the same intervention extends lifespan in that species), as `analog_probes` does for human hypotheses; without them the
curated records of other species would not reach the ranking. The protocol and the criteria are in specs/clean-2024-12-31.yaml.
"""
from __future__ import annotations

import argparse
import copy
import json
import math
import random
import re
from pathlib import Path

ITP = re.compile(r"^Dietary (?P<c>.+?)(?: \(started at (?P<age>\d+) months\))? extends the median lifespan of genetically "
                 r"heterogeneous UM-HET3 mice of at least one sex\.$")
CITP = re.compile(r"^(?P<c>.+?)(?: \(at (?P<dose>lower|higher) doses\))? extends the lifespan of Caenorhabditis nematodes across "
                  r"genetically diverse species and strains\.$")
TEMPLATE = "data/validation/l1_10_pool.json"            # an ITP card of the normalizer (UM-HET3, diet), fields reused
PROBE_SPECIES = ("mouse", "Caenorhabditis elegans", "Drosophila melanogaster")   # the DrugAge species with most records
MIN_SCORED, MIN_POSITIVES = 30, 8


def card(text: str, n: int, template: dict) -> dict:
    """The card of one pool hypothesis, by code from its text only."""
    from hyparena.tools import compounds as cp
    m, worm = ITP.match(text), False
    if m is None:
        m, worm = CITP.match(text), True
    if m is None:
        raise ValueError(f"not a pool sentence: {text!r}")
    label = m["c"]
    names = [x.strip() for x in label.split(" + ")]
    c = copy.deepcopy(template)
    c["id"] = c["raw_id"] = f"H-{n:04d}"
    ids = []
    for name in names:
        comp = cp.lookup(name)
        chebi = getattr(comp, "chebi", "") if comp else ""
        ids.append((chebi if chebi.startswith("CHEBI:") else f"CHEBI:{chebi}") if chebi else None)
    c["pico"]["intervention"] = [{"type": "compound", "label": name, "id": i, "regimen": "unknown",
                                  "route": "unknown" if worm else "diet"} for name, i in zip(names, ids)]
    c["pico"]["comparator"] = {"type": "control", "label": "untreated control"}
    q = {"measure": "median lifespan"}
    if worm:
        c["pico"]["population"] = {"taxon": "NCBITaxon:6239", "label": "Caenorhabditis nematodes",
                                   "strain": "genetically diverse species and strains", "sex": "unknown", "age_at_start": "unknown"}
        q = {"species": "Caenorhabditis elegans", "strain": "genetically diverse species and strains", "measure": "lifespan"}
        if m["dose"]:
            q["dose"] = f"{m['dose']} doses"
        obj = "Caenorhabditis nematodes"
        c["decisive_experiment"] = {"system": "worm", "endpoint": "lifespan", "duration_class": "weeks"}
    else:
        c["pico"]["population"]["age_at_start"] = f"{m['age']} months" if m["age"] else "unknown"
        q = {"species": "mouse", "strain": "UM-HET3", "sex": "at least one sex", "measure": "median lifespan"}
        if m["age"]:
            q["age_at_start"] = f"{m['age']} months"
        obj = "mouse"
    c["claim_plain"] = text
    k = next(x for x in c["claims"] if x["role"] == "outcome")
    k.update(id="c1", relation="extends_lifespan_in", object={"label": obj, "id": None, "hallmark": None}, qualifiers=q,
             source_span=text, inherited_from_pico=[], note="")
    k["subject"] = {"label": label, "id": ids[0] if len(ids) == 1 else None, "hallmark": None}
    c["claims"], c["edges"] = [k], []
    for key in [x for x in c if "alternatives" in x]:
        c[key] = []
    return c


def cards(pool_path: str) -> list[dict]:
    template = json.loads(Path(TEMPLATE).read_text())["items"][0]["card"]
    hyps = json.loads(Path(pool_path).read_text())["hypotheses"]
    return [card(h["title"], i, template) for i, h in enumerate(hyps, 1)]


def species_probes(card_obj):
    """One probe per DrugAge species other than the hypothesis' own: the same intervention extends lifespan there."""
    from hyparena.card.models import Claim, Entity
    out = card_obj.outcome_claim
    if card_obj.hypothesis_type != "interventional" or not card_obj.pico.intervention or out is None:
        return []
    own = "Caenorhabditis elegans" if "6239" in (card_obj.pico.population.taxon or "") else "mouse"
    label = " + ".join(i.label for i in card_obj.pico.intervention)
    return [Claim(id=f"sp{j}", subject=Entity(label=label), relation="extends_lifespan_in", object=Entity(label=s),
                  qualifiers={"species": s}, role="analog", note="added by the verifier (other species, curated only)")
            for j, s in enumerate((s for s in PROBE_SPECIES if s != own), 1)]


def run(pool_path: str, out: str, spec: str | None, K: int = 10000) -> dict:
    from hyparena.card import pipeline, verifier
    from hyparena.tools import pubmed
    pool = json.loads(Path(pool_path).read_text())
    pubmed.search = lambda q, retmax=8, as_of=None: []          # curated sources only: no PubMed search, no abstracts
    pubmed.fetch = lambda ids: {}
    verifier.analog_probes = species_probes
    res = pipeline.run([h["title"] for h in pool["hypotheses"]], writer="template", fake=True, as_of=pool["source"]["as_of"],
                       K=K, cards=cards(pool_path), check_alternatives=False, dedup=False, spec=spec)
    if res["meta"].get("calls"):
        raise RuntimeError(f"a model was called {res['meta']['calls']} times: the policy forbids it")
    res["meta"]["ids"] = [f"imp{i:03d}" for i in range(1, len(pool["hypotheses"]) + 1)]
    res["meta"]["pool"] = {"file": pool_path, "curated_only": True, "cards": "code template", "probes": list(PROBE_SPECIES)}
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str))
    return res


def permutation_p(pos: list, neg: list, K: int, n: int = 10000, seed: int = 0) -> float:
    """One-sided p of the tie-aware AUC under permutation of the labels over the scored units."""
    from hyparena.backtest import tied_auc
    obs = tied_auc(pos, neg, K)
    units, rng, hits = pos + neg, random.Random(seed), 0
    for _ in range(n):
        rng.shuffle(units)
        hits += tied_auc(units[:len(pos)], units[len(pos):], K) >= obs - 1e-12
    return (hits + 1) / (n + 1)


def l33(labels: dict, res: dict, K: int = 10000, perms: int = 10000) -> dict:
    """Primary: tie-aware AUC per regimen (evidence_first without late_start), known results apart, filtered at the bottom."""
    from hyparena.backtest import bootstrap_tied_auc, tied_auc, tied_scores
    from hyparena.outcomes import spearman
    score = tied_scores(labels, res, "all", K)
    known = [pid for pid, x in zip(res["meta"]["ids"], res["items"]) if x["outcome"] == "known_result"]
    pos = [score[p] for p in score if labels[p]["label"] == 1]
    neg = [score[p] for p in score if labels[p]["label"] == 0]
    out = {"n_scored": len(score), "n_pos": len(pos), "n_neg": len(neg),
           "known_results": [{"id": p, "compound": labels[p]["compound"], "label": labels[p]["label"]} for p in known],
           "outcomes": {o: sum(x["outcome"] == o for x in res["items"]) for o in {x["outcome"] for x in res["items"]}}}
    if not pos or not neg:
        return {**out, "status": "uninformative"}
    a = tied_auc(pos, neg, K)
    lo, hi = bootstrap_tied_auc(pos, neg, K)
    p = permutation_p(pos, neg, K, perms)
    status = ("uninformative" if len(score) < MIN_SCORED or len(pos) < MIN_POSITIVES
              else "pass" if p < 0.05 else "fail" if hi < 0.60 else "inconclusive")
    order = sorted(score, key=lambda h: -score[h][0])
    eff = [(score[h][0], labels[h]["effect"]) for h in score if labels[h].get("effect") is not None]
    out.update(auc=round(a, 3), auc_95ci=[round(lo, 3), round(hi, 3)], p_perm_one_sided=round(p, 4), status=status,
               precision_at_3=sum(labels[h]["label"] for h in order[:3]) / 3, base_rate=round(len(pos) / len(score), 3),
               top3=[labels[h]["compound"] for h in order[:3]],
               spearman_effect=round(spearman([x for x, _ in eff], [y for _, y in eff]), 3), n_with_effect=len(eff))
    return out


def calibration(labels: dict, res: dict, profile: str = "evidence_first") -> dict:
    """P(A>B) of the run's ranking (the full profile, as it stores pairwise probabilities) against the observed order."""
    from hyparena.outcomes import calibration as cal
    by_item = dict(zip((x["id"] for x in res["items"]), res["meta"]["ids"]))
    pw = ((res.get("ranking") or {}).get(profile) or {}).get("pairwise") or {}
    pairwise = {by_item[a]: {by_item[b]: q for b, q in row.items() if b in by_item} for a, row in pw.items() if a in by_item}
    return cal(pairwise, labels)


def l39(labels: dict, res: dict, K: int = 10000, draws: int = 10000) -> dict:
    """Our rank against the naive "approved first" order, paired over compounds (scripts/naive_baseline.py)."""
    from hyparena.backtest import tied_scores
    from scripts.naive_baseline import compound_units, naive_scores, paired
    ours = tied_scores(labels, res, "all", K)
    naive = naive_scores(res, set(ours))
    units = compound_units(labels, ours, {k: v for k, v in naive.items() if k in ours})
    out = paired(units, K, draws)
    out["path_to_human"] = {lv: sum((x.get("indicators") or {}).get("path_to_human") == lv for x in res["items"]
                                   if x["outcome"] == "ranked") for lv in ("0", "1", None)}
    return out


def evaluate(labels_path: str, run_path: str) -> dict:
    labels = json.loads(Path(labels_path).read_text())
    res = json.loads(Path(run_path).read_text())
    from hyparena import prespec
    return {"spec": res["meta"].get("spec"), "spec_problems": prespec.verify(res["meta"]["spec"]) if res["meta"].get("spec") else ["no spec"],
            "L3.3": l33(labels, res), "calibration_P(A>B)": calibration(labels, res), "L3.9": l39(labels, res)}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("cards")
    c.add_argument("--pool", required=True)
    c.add_argument("--out", required=True)
    r = sub.add_parser("run")
    r.add_argument("--pool", required=True)
    r.add_argument("--out", required=True)
    r.add_argument("--spec", default=None)
    e = sub.add_parser("evaluate")
    e.add_argument("--labels", required=True)
    e.add_argument("--run", required=True)
    a = ap.parse_args()
    if a.cmd == "cards":
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(json.dumps(cards(a.pool), ensure_ascii=False, indent=1))
    elif a.cmd == "run":
        res = run(a.pool, a.out, a.spec)
        print(a.out, res["outcome_counts"] if "outcome_counts" in res else "", "calls", res["meta"].get("calls"))
    else:
        print(json.dumps(evaluate(a.labels, a.run), indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()

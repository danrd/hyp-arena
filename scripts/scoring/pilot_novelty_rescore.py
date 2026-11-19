"""Rescore a frozen evaluation bundle without retrieval or model calls."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from unittest.mock import patch

from hyparena.card.models import HypothesisCard
from hyparena.novelty.novelty_v34 import LEVELS
from hyparena.scoring import aspid_v3, v3_extra
from hyparena.tools import compounds
from scripts.scoring.readiness_recognition_check import legacy_feasibility


def cap_novelty(level, comparison, *, broad):
    if level not in LEVELS or comparison["distinct_test"] != "no":
        return level
    relation = comparison["relation"]
    if relation == "same" and comparison["species"] in {"same", "different"}:
        cap = "translation" if comparison["species"] == "different" else "new_context"
    elif broad and relation == "related":
        cap = "analog"
    else:
        return level
    return min((level, cap), key=LEVELS.index)


def load(path):
    return json.loads(path.read_text())


def run(bundle, comparisons, cache, lookup_diagnostics):
    report = load(bundle / "full_report_data.json")
    cases = {case["id"]: case for case in load(bundle / "cases.json")}
    dossier = load(bundle / "dossier.json")
    sources = {s["source"]["source_id"]: s["source"] for s in dossier["sources"]}
    prior = {h["hypothesis_id"]: {str(sources[r["source_id"]]["pmid"]) for r in h["prior_work"]}
             for h in dossier["hypotheses"]}
    assert set(comparisons) == set(cases) == set(report["hyps"])
    scenarios = {name: {} for name in ("archive", "readiness", "readiness_and_n", "strict", "broad")}
    rows = {}

    def lookup(label, *, raise_on_error=False):
        raw = cache.get(compounds.key(compounds.resolve_alias(label)))
        return compounds.Compound(**raw) if raw else None

    for ident, case in cases.items():
        saved = report["hyps"][ident]
        values = saved["values"]
        comp = comparisons[ident]
        if comp["pmid"] not in prior[ident]:
            raise ValueError(f"Predecessor {comp['pmid']} is not in the saved dossier for {ident}")
        card = HypothesisCard.model_validate(case["card"])
        with patch.object(compounds, "lookup", side_effect=lookup):
            readiness, status = v3_extra.readiness_assessment(card)
        lookup_row = lookup_diagnostics.get(ident)
        if status == "unresolved" and lookup_row and lookup_row.get("identified") and lookup_row.get("max_phase") is None:
            status = "phase_unknown"
        with patch.object(v3_extra, "readiness", return_value=readiness):
            feasibility = v3_extra.feasibility(card)
        v3 = {k: saved[k] for k in ("P", "scope", "I", "gate")}
        v3["headroom_I"] = values["I_headroom"]
        old_level = values["N"]
        stages = {
            "archive": (values["feasibility"], old_level),
            "readiness": (legacy_feasibility(card, readiness), old_level),
            "readiness_and_n": (feasibility, old_level),
            "strict": (feasibility, cap_novelty(old_level, comp, broad=False)),
            "broad": (feasibility, cap_novelty(old_level, comp, broad=True)),
        }
        rows[ident] = {"readiness_status": status, "n_planned": card.decisive_experiment.n_planned,
                       "comparison": comp, "scenarios": {}}
        for name, (f, n) in stages.items():
            scenarios[name][ident] = (v3, dict(values, feasibility=f, N=n))
            rows[ident]["scenarios"][name] = {"feasibility": f, "N": n, "profiles": {}}

    orders = {}
    for name, inputs in scenarios.items():
        orders[name] = {}
        for profile in aspid_v3.load():
            result = aspid_v3.rank(inputs, profile, K=10000, seed=0)
            order = sorted(result.ids, key=lambda h: -round(result.expected[h], 4))
            orders[name][profile] = order
            if name == "archive" and order != report["ranks"][profile]:
                raise ValueError(f"Archived order not reproduced for {profile}")
            for rank, ident in enumerate(order, 1):
                rows[ident]["scenarios"][name]["profiles"][profile] = {
                    "rank": rank, "score": round(result.expected[ident], 4)
                }
    return {"rows": rows, "orders": orders}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ("bundle", "comparisons", "cache", "lookup-diagnostics", "out"):
        parser.add_argument(f"--{flag}", type=Path, required=True)
    args = parser.parse_args()
    diagnostics = {row["id"]: row for row in load(args.lookup_diagnostics)}
    result = run(args.bundle, load(args.comparisons), load(args.cache), diagnostics)
    args.out.write_text(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    main()

"""Offline comparison of intervention recognition rules on synthetic and optionally saved cards."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from hyparena.card.models import HypothesisCard
from hyparena.scoring import v3_extra
from hyparena.tools import compounds


def legacy_readiness(card: HypothesisCard) -> float | None:
    """Freeze the pre-fix baseline for reproducing the November pilot."""
    from hyparena.card.entities import subject_compounds

    labels = [i.label for i in card.pico.intervention]
    if not labels:
        return None
    try:
        hits = [c for label in labels for c in subject_compounds(label, card) or []]
    except Exception:
        return None
    if not hits:
        return 1.0
    phase = max(c.max_phase or 0 for c in hits)
    return 1.0 if phase >= 4 else 0.5 if phase >= 1 else 0.0


def legacy_feasibility(card: HypothesisCard, readiness: float | None) -> float | None:
    experiment = card.decisive_experiment
    parts = (v3_extra.SYSTEM_COST.get(experiment.system), v3_extra.DURATION_COST.get(experiment.duration_class),
             v3_extra._n_score(experiment.n_planned), readiness)
    known = [part for part in parts if part is not None]
    return round(sum(known) / len(known), 3) if known else None


def candidate(card: HypothesisCard) -> float | None:
    from hyparena.card.entities import subject_compounds

    interventions = card.pico.intervention
    if not interventions or any(i.type == "unspecified" or i.label.strip().casefold() in {"", "unknown"}
                                for i in interventions):
        return None
    drugs = [i for i in interventions if i.type == "compound"]
    if not drugs:
        return 1.0
    try:
        parts = [subject_compounds(i.label, card) for i in drugs]
    except compounds.LookupError_:
        return None
    if any(not part for part in parts):
        return None
    phase = max((c.max_phase or 0) for part in parts if part for c in part)
    return 1.0 if phase >= 4 else 0.5 if phase >= 1 else 0.0


def synthetic_checks() -> list[dict]:
    phases = {"approved": 4, "clinical": 2, "preclinical": 0}

    def resolver(label, _card):
        if label == "service failure":
            raise compounds.LookupError_("simulated unavailable service")
        return [SimpleNamespace(max_phase=phases[label])] if label in phases else None

    checks = [
        ("approved", [("compound", "approved")], 1.0),
        ("clinical", [("compound", "clinical")], 0.5),
        ("preclinical", [("compound", "preclinical")], 0.0),
        ("exercise", [("exercise", "specified programme")], 1.0),
        ("unresolved", [("compound", "unnamed agent")], None),
        ("partial", [("compound", "approved"), ("compound", "unnamed agent")], None),
        ("unspecified", [("unspecified", "activate the target")], None),
        ("failed lookup", [("compound", "service failure")], None),
        ("empty", [], None),
    ]
    rows = []
    with patch("hyparena.card.entities.subject_compounds", side_effect=resolver):
        for name, interventions, expected in checks:
            card = HypothesisCard.model_validate({
                "id": "fixture", "hypothesis_type": "interventional", "claim_plain": "Synthetic",
                "pico": {"intervention": [{"type": kind, "label": label} for kind, label in interventions]},
            })
            before, after = legacy_readiness(card), candidate(card)
            assert after == expected, (name, after, expected)
            rows.append({"case": name, "old": before, "candidate": after})
    return rows


def replay(cases: Path) -> list[dict]:
    cache = json.loads(compounds.CACHE.read_text())
    rows = []
    for case in json.loads(cases.read_text()):
        card = HypothesisCard.model_validate(case["card"])
        lookups = {}

        def cached_lookup(label):
            key = compounds.key(compounds.resolve_alias(label))
            raw = cache.get(key)
            lookups[key] = "absent from cache" if key not in cache else "matched" if raw else "cached miss"
            return compounds.Compound(**raw) if raw else None

        with patch.object(compounds, "lookup", side_effect=cached_lookup):
            old = legacy_readiness(card)
            after = candidate(card)
            old_feasibility = legacy_feasibility(card, old)
            new_feasibility = legacy_feasibility(card, after)
        rows.append({"id": case["id"], "lookups": sorted(lookups.values()), "old_readiness": old,
                     "candidate_readiness": after, "old_feasibility": old_feasibility,
                     "candidate_feasibility_legacy_formula": new_feasibility})
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path)
    args = parser.parse_args()
    results = {"synthetic": synthetic_checks()}
    if args.cases:
        results["replay"] = replay(args.cases)
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()

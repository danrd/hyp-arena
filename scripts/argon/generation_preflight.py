"""Validate blinded intake reviews and build pairs only from eligible candidates."""

import argparse
from itertools import combinations
import json
from pathlib import Path
import random


DISTINCT = {"new_link", "intervention_change", "tested_modifier"}
NOVELTY = DISTINCT | {"known_context", "known_species", "unresolved"}
SCORES = {"verified": 1.0, "conditional": 0.5, "unknown": 0.0}


def indexed(rows, key):
    result = {row[key]: row for row in rows}
    if len(result) != len(rows):
        raise ValueError(f"Duplicate {key}")
    return result


def evaluate(hypotheses, cases, dossier, review):
    cutoff = hypotheses["as_of"]
    if review["cutoff_date"] != cutoff or dossier["cutoff_date"] != cutoff:
        raise ValueError("Cutoff dates differ")
    texts = indexed(hypotheses["hypotheses"], "id")
    cards = indexed(cases, "id")
    dossier_rows = indexed(dossier["hypotheses"], "hypothesis_id")
    reviews = indexed(review["reviews"], "hypothesis_id")
    if not texts or texts.keys() != cards.keys() or texts.keys() != dossier_rows.keys() or texts.keys() != reviews.keys():
        raise ValueError("Expected one case, dossier entry and review per submitted hypothesis")
    pmids = {str(row["source"]["pmid"]) for row in dossier["sources"] if row["source"].get("pmid")}
    result = {}
    for ident, row in reviews.items():
        text = texts[ident]
        experiment = text["experiment"]
        novelty, scope, readiness = (row[key] for key in ("novelty", "scope", "readiness"))
        if novelty not in NOVELTY or scope not in {"target", "prerequisite", "mismatch"} or readiness not in SCORES:
            raise ValueError(f"{ident}: invalid novelty, scope or readiness")
        for key in ("known_result", "reason"):
            if not row.get(key, "").strip():
                raise ValueError(f"{ident}: {key} is required")
        refs = row["source_pmids"]
        if not isinstance(refs, list) or not {str(pmid) for pmid in refs} <= pmids or (novelty != "unresolved" and not refs):
            raise ValueError(f"{ident}: cite the dossier evidence or mark novelty unresolved")
        if novelty in DISTINCT:
            if (not anchored(row, "contrast_span", experiment)
                    or not all(row.get(k, "").strip() for k in ("increment", "refuting_result"))):
                raise ValueError(f"{ident}: the new contribution needs a stated contrast and a refuting result")
        population = cards[ident]["card"]["pico"]["population"]
        system = cards[ident]["card"]["decisive_experiment"]["system"]
        human_population = str(population.get("taxon") or "").casefold() in {"homo sapiens", "human", "humans"}
        claim_level = row["claim_level"]
        if claim_level not in {"patient", "human_tissue", "nonhuman", "analysis"} or not anchored(row, "claim_span", text["claim"]):
            raise ValueError(f"{ident}: identify the level of the original claim")
        if human_population and claim_level == "nonhuman":
            raise ValueError(f"{ident}: claim level conflicts with the card's population")
        target_systems = {"patient": {"human", "data_analysis"}, "human_tissue": {"cells", "human"}}
        if scope == "target" and claim_level in target_systems and system not in target_systems[claim_level]:
            raise ValueError(f"{ident}: the stated system cannot directly test the human claim")
        if scope == "prerequisite" and not all(row.get(k, "").strip() for k in ("tested_prerequisite", "remaining_gap")):
            raise ValueError(f"{ident}: state the tested prerequisite and remaining gap")
        if readiness != "unknown":
            implementation_refs = row.get("implementation_pmids")
            if (not anchored(row, "implementation_span", experiment)
                    or not isinstance(implementation_refs, list) or not implementation_refs
                    or not {str(pmid) for pmid in implementation_refs} <= pmids
                    or not row.get("implementation_basis", "").strip()):
                raise ValueError(f"{ident}: document an actual implementation in the stated experiment")
        if readiness == "conditional" and not row.get("remaining_gap", "").strip():
            raise ValueError(f"{ident}: identify the prerequisite for implementation")
        ready = readiness == "verified" and scope != "mismatch"
        result[ident] = {
            "novelty_ceiling": {"known_context": "new_context", "known_species": "translation"}.get(novelty),
            "novelty": novelty, "claim_level": claim_level, "scope": scope, "readiness": SCORES[readiness],
            "frontier_eligible": ready and novelty in DISTINCT,
            "clinical_priority_eligible": ready and scope == "target" and claim_level == "patient" and system == "human",
            "reason": row["reason"],
        }
    return {
        "cutoff_date": cutoff,
        "eligible_ids": {pool: sorted(h for h, row in result.items() if row[f"{pool}_eligible"])
                         for pool in ("frontier", "clinical_priority")},
        "rows": result,
    }


def anchored(row, key, source):
    quote = row.get(key, "").strip()
    return bool(quote) and quote in source


def make_pairs(ids):
    ids = list(ids)
    rng = random.Random(0)
    rng.shuffle(ids)
    n = len(ids)
    pairs = []
    for left, right in combinations(range(n), 2):
        if right - left > n // 2:
            left, right = right, left
        pairs.append([ids[left], ids[right]])
    rng.shuffle(pairs)
    return {"pairs": [{"pair_id": f"P{i:03d}", "hypothesis_ids": hs} for i, hs in enumerate(pairs, 1)]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("hypotheses", "cases", "dossier", "review", "out"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--pool", choices=("frontier", "clinical_priority"))
    parser.add_argument("--pairs-out", type=Path)
    args = parser.parse_args()
    if bool(args.pool) != bool(args.pairs_out):
        parser.error("--pool and --pairs-out must be supplied together")
    try:
        result = evaluate(*(json.loads(path.read_bytes())
                            for path in (args.hypotheses, args.cases, args.dossier, args.review)))
    except (KeyError, ValueError, TypeError) as exc:
        parser.error(str(exc))
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    if args.pairs_out:
        ids = result["eligible_ids"][args.pool]
        if len(ids) < 2:
            parser.error(f"{args.pool}: fewer than two eligible hypotheses")
        args.pairs_out.write_text(json.dumps(make_pairs(ids), indent=2) + "\n")


if __name__ == "__main__":
    main()

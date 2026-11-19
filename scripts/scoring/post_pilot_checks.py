"""Frozen-input feasibility comparison and predecessor diagnostics. No network or model calls."""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from hyparena.card.models import ClaimVerification, HypothesisCard
from hyparena.novelty import novelty_v34 as novelty
from hyparena.scoring import aspid_v3, rules_v3, rules_v32, v3_extra
from hyparena.tools import compounds
from scripts.scoring.readiness_recognition_check import candidate, legacy_feasibility, legacy_readiness, synthetic_checks


def load(path):
    return json.loads(path.read_text())


def bounds(parts):
    total = sum(value for value in parts if value is not None)
    return round(total / 4, 3), round((total + parts.count(None)) / 4, 3)


def check_bounds():
    values = (0, 1 / 3, .5, 2 / 3, 1, None)
    tested = 0
    for parts in itertools.product(values, repeat=4):
        if None not in parts:
            assert bounds(parts) == (round(sum(parts) / 4, 3),) * 2
        for i, value in enumerate(parts):
            if value is not None:
                assert bounds(parts[:i] + (None,) + parts[i + 1:])[0] <= bounds(parts)[0]
                tested += 1
    return tested


def parsed(item):
    return (HypothesisCard.model_validate(item["card"]),
            [ClaimVerification.model_validate(v) for v in item.get("verifications", (item.get("verification") or {}).get("claims", []))])


def feasibility_pool(pool, cache, target_cache):
    rows, axes = {}, {name: {} for name in ("baseline", "recognition", "lower_bound")}
    for ident, (item, saved) in pool.items():
        card, cvs = parsed(item)
        missing_cache = set()

        def lookup(label):
            key = compounds.key(compounds.resolve_alias(label))
            if key not in cache:
                missing_cache.add(key)
            raw = cache.get(key)
            return compounds.Compound(**raw) if raw else None

        with patch.object(compounds, "lookup", side_effect=lookup), patch.object(
            compounds, "target_names", side_effect=lambda ident: target_cache.get(ident, [])
        ):
            old, new = legacy_readiness(card), candidate(card)
            old_mean = legacy_feasibility(card, old)
            new_mean = legacy_feasibility(card, new)
            meta = saved.get("values", saved) if saved else {}
            if "weights" in item.get("v3", {}):
                with patch.object(v3_extra, "readiness", return_value=old):
                    extra_axes = v3_extra.extras(card, cvs, item["v3"])
                meta = {**extra_axes, **meta}
            if saved:
                v3 = {k: saved.get(k) for k in ("P", "scope", "I", "gate")}
                v3["headroom_I"] = meta.get("I_headroom")
            else:
                alts = {k: ClaimVerification.model_validate(v) for k, v in (item.get("v3_alternatives") or {}).items()}
                evaluation = rules_v32.evaluate(card, cvs, alts, v36=True)
                v3 = evaluation.as_dict()
                meta.update(chain_state=evaluation.chain_state, N=novelty.novelty(card, cvs, evaluation), ai_role=card.ai_role)
        exam = card.decisive_experiment
        parts = (v3_extra.SYSTEM_COST.get(exam.system), v3_extra.DURATION_COST.get(exam.duration_class),
                 v3_extra._n_score(exam.n_planned), new)
        lo, hi = bounds(parts)
        row = {"readiness": [old, new], "missing_cache_keys": len(missing_cache), "components": parts,
               "scores": [old_mean, new_mean, lo], "interval": [lo, hi], "saved_feasibility": saved.get("values", saved).get("feasibility") if saved else None,
               "unknown_components": [name for name, value in zip(("system", "duration", "sample_size", "readiness"), parts) if value is None],
               "sample_applicability_review": exam.system == "data_analysis" and exam.n_planned is None,
               "ranks": {}}
        rows[ident] = row
        for (group, data), score in zip(axes.items(), row["scores"]):
            data[ident] = (v3, dict(meta, feasibility=score))
    summary = {}
    for profile in ("funding", "frontier"):
        ranks = {group: aspid_v3.rank(data, profile, K=10000, seed=0).order for group, data in axes.items()}
        base = ranks["baseline"]
        summary[profile] = {group: {"ranked": len(order), "top10_overlap": len(set(base[:10]) & set(order[:10])),
                                    "max_rank_shift": max((abs(base.index(i) - j) for j, i in enumerate(order)), default=0)}
                            for group, order in ranks.items()}
        for group, order in ranks.items():
            for index, ident in enumerate(order, 1):
                rows[ident]["ranks"].setdefault(profile, {})[group] = index
    return {"rows": rows, "profiles": summary}


def predecessor_candidates(card, cvs):
    current = novelty.novelty_source(card, cvs)
    claims = {c.id: c for c in rules_v3.chain(card)}
    _, endpoints = novelty.slots(card)
    key = lambda text: " ".join(re.findall(r"\w+", text.casefold()))
    names = {key(i.label) for i in card.pico.intervention}
    identifiers = {i.id for i in card.pico.intervention if i.id}
    rows = {}
    for verification in cvs:
        claim = claims.get(verification.id)
        if not claim or (key(claim.subject.label) not in names and claim.subject.id not in identifiers):
            continue
        for against, records in ((False, verification.evidence), (True, verification.counterevidence)):
            for rec in records:
                pmid = rec.record_id.removeprefix("PMID:")
                match = rec.qualifiers_match.get("intervention_match")
                if not pmid.isdigit() or match not in ("exact", "class", "related_compound", "dose_differs", "regimen_differs"):
                    continue
                weight = rules_v32.current_weight(rec, claim, against)
                if weight <= 0:
                    continue
                priority = (claim.id not in endpoints, match != "exact", -weight, int(pmid))
                data = {"pmid": pmid, "claim_id": claim.id, "direction": "against" if against else "for",
                        "intervention_match": match, "outcome_slot": claim.id in endpoints, "weight": weight}
                if pmid not in rows or priority < rows[pmid][0]:
                    rows[pmid] = (priority, data)
    leads = [data for _, data in sorted(rows.values(), key=lambda row: row[0]) if data["pmid"] != current][:3]
    return current, leads


def predecessor_pool(pool, references):
    rows = {}
    for ident in sorted(set(pool) & set(references)):
        current, leads = predecessor_candidates(*parsed(pool[ident]))
        pmids = ([current] if current else []) + [r["pmid"] for r in leads]
        gold = set(references[ident])
        rows[ident] = {"original": current, "leads": leads, "reference": sorted(gold),
                       "baseline_hit": current in gold, "new_hit1": bool(gold.intersection(pmids[:1])),
                       "new_hit3": bool(gold.intersection(pmids[:3])),
                       "off_reference_leads": sum(r["pmid"] not in gold for r in leads)}
        assert not rows[ident]["baseline_hit"] or rows[ident]["new_hit1"]
    return rows


def check_predecessors():
    def record(pmid, match):
        return SimpleNamespace(record_id=pmid, qualifiers_match={"intervention_match": match})

    card, _ = parsed({"card": {"id": "fixture", "hypothesis_type": "interventional", "claim_plain": "Synthetic",
        "pico": {"intervention": [{"type": "compound", "label": "Agent A"}]},
        "claims": [
            {"id": "c1", "subject": {"label": "Agent A"}, "relation": "activates", "object": {"label": "Intermediate"},
             "role": "mechanism", "link": "pathway"},
            {"id": "c2", "subject": {"label": "Agent B"}, "relation": "activates", "object": {"label": "Intermediate"},
             "role": "mechanism", "link": "pathway"},
        ]}})
    cvs = [
        SimpleNamespace(id="c1", evidence=[record("1", "exact"), record("2", "different"), record("3", "exact")], counterevidence=[]),
        SimpleNamespace(id="c2", evidence=[record("4", "exact")], counterevidence=[]),
    ]
    with patch.object(novelty, "novelty_source", return_value=None), patch.object(
        rules_v32, "current_weight", side_effect=lambda r, *_: 0.0 if r.record_id == "3" else 1.0
    ):
        _, leads = predecessor_candidates(card, cvs)
        assert [r["pmid"] for r in leads] == ["1"]
    return 4


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--kg", type=Path, required=True)
    ap.add_argument("--cache", type=Path, default=compounds.CACHE)
    ap.add_argument("--target-cache", type=Path, default=compounds.TARGET_CACHE)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    kg = args.kg
    pilot = kg / "reviews/generation-2026-11-18-hy4/evaluation"
    cohort = {c["id"]: c for c in load(pilot / "cases.json")}
    scores = load(pilot / "full_report_data.json")["hyps"]
    pilot_pool = {i: (c, scores[i]) for i, c in cohort.items()}
    prospective = kg / "hypothesis_sources/prospective"
    prospective_scores = load(prospective / "scores_60_current.json")
    prospective_pool = {i: (r["items"][0], prospective_scores[i]) for i, r in load(prospective / "run_60.json").items()
                        if r.get("items") and r["items"][0].get("card") and i in prospective_scores}
    cal = kg / "hypothesis_sources/calibration"
    calibration = {i: (r["items"][0], None) for file in sorted(cal.glob("run_*_cur.json"))
                   for i, r in load(file).items() if r.get("items") and r["items"][0].get("card")}
    ref = {r["hypothesis_id"]: re.findall(r"\b[1-9]\d{6,7}\b", str(r["closest_work"]))
           for r in load(pilot / "judge_results.json")["prior_work"]}
    pack = kg / "reviews/argon-2026-11-15"
    held = {i: r["items"][0] for f in sorted(pack.glob("pack_26_run_[123].json")) + sorted(pack.glob("pack_26_run_fix_*.json"))
            for i, r in load(f).items() if r.get("items") and r["items"][0].get("card")}
    held_refs = {r["id"]: [str(p) for p in r["defining_pmids"]] for r in load(pack / "pack_26_answer.json")["hypotheses"]
                 if r.get("defining_pmids")}
    cache_bytes = args.cache.read_bytes()
    cache = json.loads(cache_bytes)
    target_bytes = args.target_cache.read_bytes() if args.target_cache.exists() else b"{}"
    target_cache = json.loads(target_bytes)
    result = {"cache_sha256": hashlib.sha256(cache_bytes).hexdigest(), "mask_checks": check_bounds(),
              "target_cache_sha256": hashlib.sha256(target_bytes).hexdigest(),
              "predecessor_fixture_checks": check_predecessors(),
              "recognition_checks": synthetic_checks(),
              "feasibility": {name: feasibility_pool(data, cache, target_cache) for name, data in
                              (("pilot", pilot_pool), ("prospective", prospective_pool), ("calibration", calibration))},
              "predecessors": {"pilot": predecessor_pool(cohort, ref), "pack26": predecessor_pool(held, held_refs)}}
    args.out.write_text(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    main()

"""Offline endpoint-comparability diagnostic. It does not alter novelty or evidence."""
from __future__ import annotations

import argparse
import json
import re
import unicodedata
from pathlib import Path

# A narrow function, its umbrella domain, and its measurement role.
MEASURES = (
    (r"\b(?:gait speed|walking speed|time to walk|10 meter walk time)\b", "walking_speed", "mobility", "function"),
    (r"\b(?:6 minute walk|six minute walk|6mwd)\b", "walking_endurance", "mobility", "function"),
    (r"\b(?:handgrip|grip strength)\b", "grip_strength", "muscular", "function"),
    (r"\b(?:quadriceps strength|knee extension strength|contractile torque)\b", "leg_strength", "muscular", "function"),
    (r"\b(?:aversive freezing|fear conditioning|episodic memory|contextual memory)\b", "memory", "cognition", "function"),
    (r"\battention\b", "attention", "cognition", "function"),
    (r"\bexecutive\b", "executive_function", "cognition", "function"),
    (r"\b(?:complete (?:ulcer |epithelial |wound )closure|(?:ulcer |wound )?reepithelialization|epithelial wound closure)\b",
     "wound_closure", "wound_healing", "function"),
    (r"\b(?:ulcer area|ulcer size|wound area)\b", "wound_area", "wound_healing", "function"),
    (r"\brecurrence free\b", "durable_healing", "wound_healing", "function"),
    (r"\b(?:ulcer healing outcomes?|vlu healing outcomes?|wound healing outcomes?)\b",
     "wound_generic", "wound_healing", "generic"),
    (r"\b(?:fmd|flow mediated dilation|flow mediated vasodilation)\b", "fmd", "vascular_reactivity", "proxy"),
    (r"\bendothelium dependent vasodilation\b", "vascular_dilation", "vascular_reactivity", "proxy"),
    (r"\b(?:vo2 peak|vo₂ peak|peak oxygen uptake)\b", "aerobic_capacity", "mobility", "function"),
    (r"\b(?:tewl|transepidermal water loss)\b", "water_loss", "skin_barrier", "proxy"),
    (r"\b(?:speech in noise|word recognition in noise)\b", "speech_in_noise", "hearing", "function"),
    (r"\b(?:abr wave|dpoae\w*|otoacoustic emissions)\b", "auditory_physiology", "hearing", "proxy"),
    (r"\b(?:bone strength|torsion strength|fracture biomechanical strength)\b",
     "bone_strength", "bone_healing", "function"),
    (r"\b(?:mineralized callus|bone volume|histomorphometry)\b", "bone_structure", "bone_healing", "proxy"),
    (r"\b(?:regenerative fibre formation|myoblast fusion|myoblast differentiation)\b",
     "muscle_cells", "muscular", "mechanism"),
    (r"\b(?:il 6|microglial activation|cx26|connexin\s*26|connexin\s*30|endocochlear potential|"
     r"osteogenic markers|differentiation marker\w*|senescence associated phenotypes|keratinocytes|pinacidil)\b",
     "mechanistic_marker", "mechanism", "mechanism"),
)
CONTEXTS = {
    "perioperative": r"\b(?:perioperative|postoperative|preoperative|after surgery)\b",
    "chronic_progression": r"\b(?:chronic dementia|progressive dementia|chronic cognitive decline)\b",
}


def normalize(text):
    value = unicodedata.normalize("NFKC", text or "").casefold()
    return " ".join(re.findall(r"\w+", value))


def describe(text):
    normalized = normalize(text)
    marks = {item[1:] for item in MEASURES if re.search(item[0], normalized)}
    contexts = {name for name, pattern in CONTEXTS.items() if re.search(pattern, normalized)}
    return marks, contexts


def incomplete_composite(text):
    parts = [part for part in re.split(r"\band\b|[,;/]", text or "", flags=re.IGNORECASE) if normalize(part)]
    return len(parts) > 1 and any(not describe(part)[0] for part in parts)


def compare(target, measured, endpoint_type=None):
    t, tc = describe(target)
    s, sc = describe(measured)
    if not normalize(target) or normalize(target) == "unknown" or not normalize(measured):
        return "unknown"
    if endpoint_type in {"biomarker", "mechanism"} or (
        s and all(role == "mechanism" for _, _, role in s)
    ) or re.search(r"\b(?:marker|predictor|biomarker) of\b", normalize(measured)):
        return "mechanism_only"
    if not t or not s:
        return "unknown"
    if tc and sc and not tc.intersection(sc):
        return "different"
    incomplete = incomplete_composite(target) or incomplete_composite(measured)
    if t == s and all(role == "function" for _, _, role in t) and not incomplete:
        return "same"
    domain = lambda tags: {family for _, family, role in tags if role != "mechanism"}
    if domain(t).intersection(domain(s)):
        return "related"
    return "unknown" if incomplete else "different"


def controls():
    return [
        ("gait speed", "walking speed", None, "same"),
        ("10-meter walk time", "time to walk 10 meters", None, "same"),
        ("speech-in-noise recognition", "word recognition in noise", None, "same"),
        ("6-minute walk distance", "gait speed", None, "related"),
        ("walking speed", "grip strength", None, "different"),
        ("postoperative executive function", "postoperative fear conditioning", None, "related"),
        ("postoperative executive function", "executive function in chronic dementia", None, "different"),
        ("memory", "IL-6 marker of memory", "biomarker", "mechanism_only"),
        ("speech-in-noise", "connexin 26 protein", None, "mechanism_only"),
        ("walking speed", "gait speed", "biomarker", "mechanism_only"),
        ("complete ulcer closure and recurrence-free healing", "complete wound closure", None, "related"),
        ("time to complete closure", "venous leg ulcer healing outcomes", None, "unknown"),
        ("complete ulcer closure", "venous leg ulcer healing outcomes", None, "related"),
        ("brachial FMD", "endothelium-dependent vasodilation", None, "related"),
        ("memory", "cognitive performance", None, "unknown"),
        ("gait speed", "", None, "unknown"),
        ("attention", "executive function", None, "related"),
        ("gait speed and fatigue score", "walking speed", None, "related"),
        ("gait speed and executive function", "executive function and walking speed", None, "same"),
    ]


def measures(card):
    outcomes = [c.get("qualifiers", {}).get("measure") for c in card["claims"] if c.get("link") == "outcome"]
    claimed = (" and ".join(outcomes) if outcomes and all(normalize(outcome) not in {"", "unknown"} for outcome in outcomes)
               else card["pico"]["outcome"].get("metric", ""))
    experiment = card["decisive_experiment"]
    planned = " and ".join(experiment.get("primary_outcomes") or [experiment.get("primary_outcome", "")])
    return claimed, planned


def read_outcomes(verifications, pmids):
    return [
        {"pmid": r["record_id"].removeprefix("PMID:"), "link": v["id"], "measure": r.get("outcome_measure"),
         "endpoint_type": r.get("endpoint"), "link_match": r.get("outcome_match"), "has_quote": bool(r.get("quote"))}
        for v in verifications for field in ("evidence", "counterevidence", "no_stance") for r in v.get(field, [])
        if r["record_id"].removeprefix("PMID:") in pmids
    ]


def assess(card, observations):
    claim, primary = measures(card)
    return {"claim_measure": claim, "primary_measure": primary,
            "observations": [{**o, "claim_comparison": compare(claim, o["measure"], o["endpoint_type"]),
                              "primary_comparison": compare(primary, o["measure"], o["endpoint_type"])}
                             for o in observations]}


def load(path):
    return json.loads(path.read_text())


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--kg", type=Path, required=True)
    cli.add_argument("--out", type=Path, required=True)
    args = cli.parse_args()
    fixtures = []
    for target, source, kind, expected in controls():
        got = compare(target, source, kind)
        assert got == expected, (target, source, got, expected)
        fixtures.append({"target": target, "source": source, "expected": expected, "got": got})

    pilot = args.kg / "reviews/generation-2026-11-18-hy4"
    refs = load(pilot / "feedback-2026-11-18/novelty-comparisons-2026-11-19.json")
    dossier = load(pilot / "evaluation/dossier.json")
    pilot_rows = {}
    for case in load(pilot / "evaluation/cases.json"):
        ident = case["id"]
        pmid = refs[ident]["pmid"]
        reader = read_outcomes(case["verifications"], {pmid})
        ds = [{"pmid": pmid, "measure": o["endpoint"], "endpoint_type": o["endpoint_type"],
               "has_quote": any(f.get("text") for f in o.get("source_fragments", []))}
              for source in dossier["sources"] if str(source["source"]["pmid"]) == pmid for o in source["observations"]]
        pilot_rows[ident] = {"reader": assess(case["card"], reader), "dossier": assess(case["card"], ds)}

    pack = args.kg / "reviews/argon-2026-11-15"
    packs = sorted(pack.glob("pack_26_run_[123].json")) + sorted(pack.glob("pack_26_run_fix_*.json"))
    saved = {key: r["items"][0] for f in packs for key, r in load(f).items()
             if r.get("items") and r["items"][0].get("card")}
    pack_rows = {}
    for row in load(pack / "pack_26_answer.json")["hypotheses"]:
        ident = row["id"]
        references = {str(pmid) for pmid in row.get("defining_pmids") or []}
        if not references or ident not in saved:
            continue
        item = saved[ident]
        reader = read_outcomes((item.get("verification") or {}).get("claims", []), references)
        pack_rows[ident] = assess(item["card"], reader)
    args.out.write_text(json.dumps({"fixtures": fixtures, "pilot": pilot_rows, "pack26": pack_rows}, indent=2) + "\n")


if __name__ == "__main__":
    main()

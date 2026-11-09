"""Argon pack 13 (user choice 2026-11-09, variant V): every record the claim-vs-results check changed or proposed to change.
Private output only (longevity-kg), it quotes papers.

    python -m scripts.pack13_claim_results     # -> reviews/argon-2026-11-08/pack_13_task.json, pack_13_key.json
"""
from __future__ import annotations

import hashlib
import json

from scripts.claim_results import CHANGE, verdict
from scripts.fulltext_reread import ARGON, targets
from scripts.v34_check import CAL, PROS


def main() -> dict:
    items, key = [], {}
    for pool, base in (("prospective", PROS), ("calibration", CAL)):
        cr = json.loads((base / "claim_results.json").read_text())
        claims = {t[0]: (t[1], t[2], t[4]) for t in targets(pool)}
        for k, r in cr.items():
            a = r.get("first") or {}
            if a.get("y_between_groups") not in CHANGE:
                continue
            h, as_of, cl = claims[k]
            key_id = hashlib.sha1(f"pack13|{k}".encode()).hexdigest()[:8]
            items.append({"id": key_id, "pmid": k.split("|")[2], "trial_registry_id": h,
                          "claim": f"{cl.subject.label} — {cl.relation.replace('_', ' ')} — {cl.object.label}",
                          "claim_qualifiers": {x: y for x, y in cl.qualifiers.items() if y},
                          "outcome_Y": cl.object.label})
            key[key_id] = {"pool": pool, "key": k, "ours": a.get("y_between_groups"), "counted": verdict(r),
                           "quote": a.get("quote"), "outcomes_quote": a.get("outcomes_quote"),
                           "other_significant": a.get("other_outcomes_significant")}
    items.sort(key=lambda x: x["id"])
    task = {
        "task": "Argon pack 13: does the trial's own full text show a between-group effect on the claim's outcome?",
        "instructions": (
            "For each item open the paper (PMID) and read its RESULTS and TABLES in the full text, not only the abstract. "
            "Answer: (1) y_between_groups: is there a statistically significant difference BETWEEN the randomised groups on "
            "the outcome Y of the claim (or a directly equivalent measure) at the primary time point: yes | no | not_measured "
            "(Y is not an outcome of the trial) | unclear | full_text_unavailable. A within-group change is not a "
            "between-group difference. (2) evidence: the sentence or table row that answers (1), copied exactly. "
            "(3) closest_measured: if not_measured, the trial outcome closest to Y and whether it is a fair stand-in "
            "(yes / no). (4) note: one sentence if the claim's qualifiers (population, dose, duration) change the answer. "
            "Reply with one JSON object {\"items\": [{\"id\": ..., \"y_between_groups\": ..., \"evidence\": ..., "
            "\"closest_measured\": ..., \"fair_stand_in\": ..., \"note\": ...}]}."),
        "items": items}
    (ARGON / "pack_13_task.json").write_text(json.dumps(task, indent=1, ensure_ascii=False) + "\n")
    (ARGON / "pack_13_key.json").write_text(json.dumps(key, indent=1, ensure_ascii=False) + "\n")
    return {"items": len(items), "counted": sum(v["counted"] != "for" for v in key.values())}


if __name__ == "__main__":
    print(json.dumps(main(), indent=1))

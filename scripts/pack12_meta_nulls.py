"""Argon pack 12: meta-analyses read as for, RCTs read as against (specs/meta-and-nulls-2026-11-09.yaml). Free.

    python -m scripts.pack12_meta_nulls build
"""
from __future__ import annotations

import hashlib
import json
import sys

from hyparena.card import rules_v3 as r3
from hyparena.card import rules_v32 as r32
from hyparena.tools import pmc, pubmed
from scripts.reread_v11 import items
from scripts.v34_check import CAL

DIR = CAL.parents[1] / "reviews" / "argon-2026-11-08"
INSTRUCTIONS = """You check, from the open-access full text in PubMed Central (use the PMCID; no other source), whether the abstract of a paper
gives a fair picture of its result on one CLAIM (a link of a hypothesis: subject - relation - object, with qualifiers).
Each item says its kind.

kind "meta_analysis_for" (our reader took the meta-analysis as evidence FOR the claim). From the full text, for the claim's
outcome: trials and participants pooled; the pooled effect with its interval; I2; GRADE certainty if reported (high /
moderate / low / very low / not reported); risk of bias of the included trials (low / some concerns / high / not reported);
abstract_overstates yes / no with kinds from low_certainty_not_in_abstract, high_heterogeneity,
small_study_or_publication_bias, outcome_not_pooled, subgroup, other; and the full-text sentence that shows it.

kind "rct_against" (our reader took the trial as evidence AGAINST the claim: a null or the opposite). From the full text:
was the claim's outcome the primary one (yes / no); the sample size calculation (the effect it was powered for and the n)
and whether that n was analysed; the result with its interval; adherence if reported; abstract_understates yes / no with
kinds from underpowered, positive_on_claim_outcome_left_out, positive_in_itt_or_secondary, equivalence_or_noninferiority,
other; and the full-text sentence that shows it.

If the full text cannot be opened, status "unavailable".

Answer with one JSON object, nothing else:
{"task": "meta_nulls", "items": [{"id": "M01", "kind": "...", "status": "read | unavailable",
  "pooled": {"trials": null, "participants": null, "effect": "", "i2": "", "grade": "", "risk_of_bias": ""},
  "trial": {"claim_outcome_primary": null, "sample_size_calc": "", "reached": null, "result": "", "adherence": ""},
  "abstract_overstates": "yes | no | n/a", "abstract_understates": "yes | no | n/a", "kinds": [], "evidence": ""}]}
"""


def build() -> dict:
    ma, nul = {}, {}
    for pool in ("prospective", "calibration"):
        for h, as_of, card, cvs, logs in items(pool):
            cl = {x.id: x for x in card.claims}
            for cv in cvs:
                k = cl.get(cv.id)
                if not k or k.link in r3.PRECLINICAL_LINKS:
                    continue
                for side, lst in (("for", cv.evidence), ("against", cv.counterevidence)):
                    for r in lst:
                        d = r3.record_design(r)
                        if r32.current_weight(r, k, side == "against") <= 0:
                            continue
                        p = r.record_id.replace("PMID:", "")
                        if side == "for" and d == "meta_analysis":
                            ma.setdefault(p, (pool, h, k))
                        elif side == "against" and d == "rct":
                            nul.setdefault(p, (pool, h, k))

    def pick(d, n):
        out = []
        for p in sorted(d, key=lambda x: hashlib.sha1(f"mn|{x}".encode()).hexdigest()):
            if len(out) >= n:
                break
            pc = pmc.pmcid(p)
            if pc and pmc.is_open(pc):
                out.append((p, pc, d[p]))
        return out
    sel = [("meta_analysis_for", x) for x in pick(ma, 20)] + [("rct_against", x) for x in pick(nul, 20)]
    meta = pubmed.fetch([p for _, (p, _, _) in sel])
    sel.sort(key=lambda s: hashlib.sha1(f"order12|{s[1][0]}".encode()).hexdigest())
    task, key = [], {}
    for i, (kind, (p, pc, (pool, h, k))) in enumerate(sel, 1):
        iid = f"M{i:02d}"
        task.append({"id": iid, "kind": kind, "pmid": p, "pmcid": pc, "title": meta.get(p, {}).get("title", ""),
                     "abstract": meta.get(p, {}).get("abstract", ""),
                     "claim": f"{k.subject.label} - {k.relation.replace('_', ' ')} - {k.object.label}", "qualifiers": k.qualifiers})
        key[iid] = {"kind": kind, "pool": pool, "unit": h, "claim": k.id, "pmid": p}
    (DIR / "pack_12_task.json").write_text(json.dumps({"task": "meta_nulls", "instructions": INSTRUCTIONS, "items": task},
                                                      indent=1, ensure_ascii=False) + "\n")
    (DIR / "pack_12_key.json").write_text(json.dumps(key, indent=1) + "\n")
    return {"meta_analyses_for": len(ma), "rct_against": len(nul), "picked": {k: sum(1 for x, _ in sel if x == k) for k in ("meta_analysis_for", "rct_against")},
            "size_kb": round((DIR / "pack_12_task.json").stat().st_size / 1024)}


if __name__ == "__main__":
    print(json.dumps({"build": build}[sys.argv[1] if len(sys.argv) > 1 else "build"](), indent=1))

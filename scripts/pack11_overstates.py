"""Argon pack 11: does the abstract overstate the trial? (specs/abstract-overstates-2026-11-09.yaml). Free (PubMed / Europe PMC).

    python -m scripts.pack11_overstates build
"""
from __future__ import annotations

import hashlib
import json
import re
import sys

from hyparena.card import rules_v3 as r3
from hyparena.card import rules_v32 as r32
from hyparena.tools import pmc, pubmed
from scripts.reread_v11 import items
from scripts.v34_check import CAL

DIR = CAL.parents[1] / "reviews" / "argon-2026-11-08"
SUB = re.compile(r"subgroup|sub-group|post[- ]hoc|per[- ]protocol|among (those|patients|participants) (who|with)|"
                 r"in (those|patients|participants) who|completers", re.I)
PRIM = re.compile(r"primary (outcome|end ?point)", re.I)
INSTRUCTIONS = """You check whether a trial's abstract overstates what the trial found, the way a systematic reviewer would.

Each item is one paper (PMID, PMCID open access in PubMed Central, title, abstract) and the CLAIM it was used for (one
link of a hypothesis: subject - relation - object, with qualifiers). Our reader took the paper as evidence FOR the claim.

For each paper:
A. From the ABSTRACT given here: finding on the claim (for / against / none), the quote, the comparison (between_groups /
   within_group / pooled / none).
B. From the open-access FULL TEXT in PMC (use the PMCID; no other source): the same fields, with the full-text quote.
   If it cannot be opened, status "unavailable".
C. abstract_overstates: yes / no. "yes" when the full text shows the trial's result on the claim is weaker than the
   abstract suggests, with kind(s) from: primary_omitted (the primary outcome's null or negative result is left out of the
   abstract), subgroup (the positive result holds only in a subgroup), secondary_as_main (a secondary or exploratory outcome
   is presented as the main result), within_group_as_between (a within-group change is presented while the between-group
   difference is null), per_protocol_only (positive only in a per-protocol or completers analysis), other. Give the
   full-text sentence that shows it.

Answer with one JSON object, nothing else:
{"task": "overstates", "items": [{"id": "O01", "A": {"finding": "", "quote": "", "comparison": ""},
  "B": {"status": "read | unavailable", "finding": "", "quote": "", "comparison": ""},
  "abstract_overstates": "yes | no", "kinds": [], "evidence": ""}]}
"""


def build() -> dict:
    flagged, unflagged = {}, {}
    for pool in ("prospective", "calibration"):
        for h, as_of, card, cvs, logs in items(pool):
            cl = {x.id: x for x in card.claims}
            for cv in cvs:
                k = cl.get(cv.id)
                if not k or k.link in r3.PRECLINICAL_LINKS:
                    continue
                for r in cv.evidence:
                    if r3.record_design(r) != "rct" or r32.current_weight(r, k, False) <= 0:
                        continue
                    p = r.record_id.replace("PMID:", "")
                    flagged.setdefault(p, None)
                    unflagged.setdefault(p, None)
                    entry = (pool, h, as_of, k, r)
                    a = pubmed.fetch([p]).get(p, {}).get("abstract", "")
                    if SUB.search(r.quote) or "subgroup_only" in r.flags or PRIM.search(a):
                        flagged[p] = flagged[p] or entry
                    else:
                        unflagged[p] = unflagged[p] or entry
    flagged = {p: e for p, e in flagged.items() if e}
    unflagged = {p: e for p, e in unflagged.items() if e and p not in flagged}

    def pick(d, n):
        out = []
        for p in sorted(d, key=lambda x: hashlib.sha1(f"over|{x}".encode()).hexdigest()):
            if len(out) >= n:
                break
            pc = pmc.pmcid(p)
            if pc and pmc.is_open(pc):
                out.append((p, pc, d[p]))
        return out
    sel = [("targeted", x) for x in pick(flagged, 40)] + [("control", x) for x in pick(unflagged, 20)]
    meta = pubmed.fetch([p for _, (p, _, _) in sel])
    sel.sort(key=lambda s: hashlib.sha1(f"order|{s[1][0]}".encode()).hexdigest())   # the arm is hidden from Argon
    task, key = [], {}
    for i, (arm, (p, pc, (pool, h, as_of, k, r))) in enumerate(sel, 1):
        iid = f"O{i:02d}"
        task.append({"id": iid, "pmid": p, "pmcid": pc, "title": meta.get(p, {}).get("title", ""), "abstract": meta.get(p, {}).get("abstract", ""),
                     "claim": f"{k.subject.label} - {k.relation.replace('_', ' ')} - {k.object.label}", "qualifiers": k.qualifiers})
        key[iid] = {"arm": arm, "pool": pool, "unit": h, "claim": k.id, "pmid": p}
    (DIR / "pack_11_task.json").write_text(json.dumps({"task": "overstates", "instructions": INSTRUCTIONS, "items": task},
                                                      indent=1, ensure_ascii=False) + "\n")
    (DIR / "pack_11_key.json").write_text(json.dumps(key, indent=1) + "\n")
    return {"flagged_papers": len(flagged), "unflagged_papers": len(unflagged),
            "targeted": sum(1 for a, _ in sel if a == "targeted"), "control": sum(1 for a, _ in sel if a == "control"),
            "size_kb": round((DIR / "pack_11_task.json").stat().st_size / 1024)}


if __name__ == "__main__":
    print(json.dumps({"build": build}[sys.argv[1] if len(sys.argv) > 1 else "build"](), indent=1))

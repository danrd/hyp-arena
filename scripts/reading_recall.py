"""Reading recall diagnostics (docs/plans/reading-recall-2026-11-08.md, steps 1-2, free).

    python -m scripts.reading_recall      # -> calibration/reading_recall.json
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict

from hyparena.card import rules_v3 as r3
from hyparena.card import rules_v32 as r32
from scripts.v34_check import CAL, PROS, parts

ARGON = CAL.parents[1] / "reviews" / "argon-2026-11-08"


def lost_reasons() -> dict:
    """Why the key papers of pack 8 that were read for their link left no record there."""
    ans = {t["id"]: t for t in json.loads((ARGON / "pack_8_answer.json").read_text())["trials"]}
    run = json.loads((PROS / "run_60.json").read_text())
    c, examples = Counter(), defaultdict(list)
    for h, t in ans.items():
        r = run[h]
        card, cvs, alts = parts(r["items"][0], h)
        by = {cv.id: cv for cv in cvs}
        claims = {cl.id: cl for cl in card.claims}
        logs = {x.get("claim"): x.get("pmids", []) for x in r["calls"] if x.get("kind") == "search"}
        replies = defaultdict(str)
        for x in r["calls"]:
            if str(x.get("template", "")).startswith("verify_claim"):
                m = re.search(r"Claim (\w+) \(", x.get("prompt", ""))
                if m:
                    replies[m.group(1)] += x.get("reply", "") or ""
        for l in t["links"]:
            cid, cv, cl = l["id"], by.get(l["id"]), claims.get(l["id"])
            if cl is None:
                continue
            for p in set(l.get("pmids_for", []) + l.get("pmids_against", [])):
                if p not in logs.get(cid, []):
                    continue
                rid = f"PMID:{p}"
                recs = [(s, x) for s, lst in (("for", cv.evidence), ("against", cv.counterevidence)) for x in lst if x.record_id == rid] if cv else []
                if any(r32.current_weight(x, cl, s == "against") > 0 for s, x in recs):
                    continue                                      # a counting record: not lost
                if recs:
                    x = recs[0][1]
                    why = ("not a finding (background, speculation)" if not r3.usable(x, r32.VARIANT_BASE)
                           else "another intervention altogether, or a context the code drops" if r32.context_v34(x, cl) is None
                           else "weight 0 (other)")
                elif cv and any(x.record_id == rid for x in cv.no_stance):
                    why = "read, stance 'neither'"
                elif cv and any(x.record_id == rid for x in cv.refusals):
                    why = "refused by code: " + next(x.type for x in cv.refusals if x.record_id == rid)
                elif p in replies.get(cid, ""):
                    why = "in the reply, dropped by code (quote not verbatim or invalid fields)"
                else:
                    why = "not mentioned in the reply at all"
                c[why] += 1
                if len(examples[why]) < 3:
                    examples[why].append(f"{h} {cid} PMID {p}")
    return {"reasons": dict(c.most_common()), "total": sum(c.values()), "examples": dict(examples)}


def cross_link_cost(pool: str) -> dict:
    """Reading volume if each chain link read the union of the papers retrieved for every claim of its trial."""
    files = [PROS / "run_60.json"] if pool == "prospective" else [CAL / f"run_{s}_v10.json" for s in (1, 2, 3, 4, 5)]
    now = union_chain = union_all = links = 0
    tin = abstracts = 0
    for f in files:
        for h, r in json.loads(f.read_text()).items():
            it = r["items"][0]
            if not (it.get("card") and it.get("verification") and "v3" in it):
                continue
            card, _, _ = parts(it, h)
            logs = {x.get("claim"): x.get("pmids", []) for x in r["calls"] if x.get("kind") == "search"}
            chain = [c.id for c in r3.chain(card)]
            u_chain = {p for cid in chain for p in logs.get(cid, [])}
            u_all = {p for v in logs.values() for p in v}
            for cid in chain:
                links += 1
                now += len(logs.get(cid, []))
                union_chain += len(u_chain)
                union_all += len(u_all)
            for x in r["calls"]:
                if str(x.get("template", "")).startswith("verify_claim"):
                    tin += int(x.get("tokens_in") or 0)
            abstracts += sum(len(v) for v in logs.values())
    per_abs = tin / abstracts if abstracts else 0
    usd = lambda n: round(n * per_abs * 0.15e-6 * 1.12, 3)        # input at 0.15 / M plus about 12% for the output
    return {"pool": pool, "chain_links": links, "papers_read_now": now, "papers_if_union_of_chain_searches": union_chain,
            "papers_if_union_of_all_searches": union_all, "tokens_per_paper": round(per_abs),
            "usd_offpeak": {"now": usd(now), "union_chain": usd(union_chain), "union_all": usd(union_all)},
            "mean_papers_per_link": {"now": round(now / links, 1), "union_chain": round(union_chain / links, 1),
                                      "union_all": round(union_all / links, 1)}}


def main() -> dict:
    out = {"lost_reasons_pack8": lost_reasons(), "cost": [cross_link_cost("prospective"), cross_link_cost("calibration")]}
    (CAL / "reading_recall.json").write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    return out


if __name__ == "__main__":
    print(json.dumps(main(), indent=1, ensure_ascii=False))

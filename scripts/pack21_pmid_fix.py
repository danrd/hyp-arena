"""Argon pack 21: the right PMIDs for the papers of the search gold (pack 18) whose number points to another paper. Free,
deterministic, no model call.

    python -m scripts.pack21_pmid_fix build   # longevity-kg/reviews/argon-2026-11-14/pack_21_task.json, pack_21_key.json
    python -m scripts.pack21_pmid_fix apply   # after the answer: checks each new PMID against PubMed and writes the fixed gold

The code check of pack 18 (scripts/bench_search.py described) found 49 of 152 PMIDs under which PubMed holds another paper
than the one described, 2 PMIDs not in PubMed and 4 invalid closest-prior-work PMIDs. Each item gives Argon's own
description, the PMID given and what PubMed holds under it; the answer names the paper (PMID, title, first author, journal,
year) or says it cannot be found. `apply` accepts a new PMID only when PubMed's title matches the title given, the first
author matches, the description fits the title and abstract (the described-check) and the date is on or before T.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from scripts import bench_search as bs

KG = Path(__file__).resolve().parents[2] / "longevity-kg"
OUT = KG / "reviews" / "argon-2026-11-14"

INSTRUCTIONS = """You earlier built a gold standard for a literature search (task search_gold_v1): for each registered trial,
the papers published on or before a date T that a careful search must find. A code check against PubMed found that for the
items below the PMID does not belong to the paper you described: PubMed holds a different paper under that number (shown as
`pubmed_has`), or the number is not in PubMed. The descriptions look like real papers; only the numbers are wrong.

For each item find the paper your description refers to and give its real identifiers. Open the PubMed record of the PMID
you give and copy the title and the first author's surname from it: the code will compare them with PubMed, and a PMID whose
record does not match is rejected. If you cannot find such a paper in PubMed, or you are not sure it exists, say so
(found: false) - do not give a nearby paper as a substitute without marking it (substitute: true). The paper must be
published on or before T.

Answer format (JSON):
{"task": "search_gold_pmid_fix_v1", "items": [
  {"id": "F01", "found": true, "pmid": "12345678", "title": "the title as PubMed gives it", "first_author": "Surname",
   "journal": "as PubMed gives it", "year": 2015, "substitute": false, "note": ""},
  {"id": "F02", "found": false, "note": "no such paper found; the description mixed two studies"}
]}
substitute: true when the paper you give is not the one described but the closest real paper that shows the same thing; say
in `note` how it differs. Nothing else is needed: categories and the rest of the gold stay as they are.
"""


def build() -> dict:
    _, key, _ = bs._load()
    ans = bs.gold_answer(original=True)
    pm = json.loads((bs.DIR / "pack_18_pubmed.json").read_text())
    items, keyd, seen = [], {}, {}
    for sid, g in sorted(ans.items()):
        T = key[sid]["T"]
        rows = [("paper", p["pmid"], p.get("shows", ""), p.get("year"), p.get("category")) for p in g["papers"]]
        cp = g["closest_prior_work"]
        if cp.get("pmid"):
            rows.append(("closest_prior_work", cp["pmid"], cp.get("differs", ""), cp.get("year"), None))
        for role, pmid, desc, year, cat in rows:
            if bs.valid(pm, pmid):
                continue
            if pmid in seen:                                   # the same wrong PMID as a paper and as the closest prior work
                keyd[seen[pmid]]["roles"].append(role)
                continue
            fid = f"F{len(items) + 1:02d}"
            seen[pmid] = fid
            info = pm.get(pmid, {})
            items.append({"id": fid, "trial_title": _title(key[sid], sid), "T": T, "description": desc, "year_given": year,
                          "pmid_given": pmid,
                          "pubmed_has": info.get("title") if info.get("exists") else "this PMID is not in PubMed"})
            keyd[fid] = {"sid": sid, "pmid_given": pmid, "roles": [role], "category": cat, "T": T}
    OUT.mkdir(parents=True, exist_ok=True)
    task = {"task": "search_gold_pmid_fix_v1", "written_on": "2026-11-14", "instructions": INSTRUCTIONS, "items": items}
    (OUT / "pack_21_task.json").write_text(json.dumps(task, indent=1, ensure_ascii=False) + "\n")
    (OUT / "pack_21_key.json").write_text(json.dumps(keyd, indent=1, ensure_ascii=False) + "\n")
    return {"items": len(items), "trials": len({k["sid"] for k in keyd.values()})}


def _title(k: dict, sid: str) -> str:
    task = {i["id"]: i for i in json.loads((bs.DIR / "pack_18_task.json").read_text())["items"]}
    m = re.search(r"^Title:\s*(.+)$", task[sid]["text"], re.M)
    return m.group(1).strip() if m else ""


def _same(a: str, b: str) -> bool:
    ta, tb = bs._content(a), bs._content(b)
    return bool(ta and tb) and len(ta & tb) / min(len(ta), len(tb)) >= 0.7


def apply() -> dict:
    """Check every new PMID against PubMed and write the corrected gold (pack_18_answer_fixed.json): an accepted PMID replaces
    the wrong one; a rejected or not-found paper is removed from the gold; a substitute is kept and marked."""
    from hyparena.tools import pubmed
    key = json.loads((OUT / "pack_21_key.json").read_text())
    task = {i["id"]: i for i in json.loads((OUT / "pack_21_task.json").read_text())["items"]}
    ans = {i["id"]: i for i in json.loads((OUT / "pack_21_answer.json").read_text())["items"]}
    pmf = bs.DIR / "pack_18_pubmed.json"
    pm = json.loads(pmf.read_text())
    ids = [str(a["pmid"]) for a in ans.values() if a.get("found") and a.get("pmid")]
    bs.summaries(ids, pm)
    rec = {}
    for i in range(0, len(ids), 50):
        rec.update(pubmed.fetch(ids[i:i + 50]))
    out, n = {}, {"accepted": 0, "substitute": 0, "not_found": 0, "rejected": 0}
    for fid, k in key.items():
        a = ans.get(fid) or {}
        if not a.get("found") or not a.get("pmid"):
            out[fid] = {"status": "not_found", "note": a.get("note", "")}; n["not_found"] += 1
            continue
        pmid = str(a["pmid"]); info = pm.get(pmid, {}); r = rec.get(pmid) or {}
        why = []
        if not info.get("exists"):
            why.append("not in PubMed")
        else:
            if not _same(a.get("title", ""), info.get("title", "")):
                why.append(f"title differs from PubMed ({info.get('title', '')[:80]!r})")
            if (a.get("first_author") or "").lower()[:5] not in (info.get("first_author") or "").lower():
                why.append(f"first author differs ({info.get('first_author')})")
            d = bs._content(task[fid]["description"])
            share = round(len(d & bs._content(f"{info.get('title', '')} {r.get('abstract', '')}")) / len(d), 2) if d else 0
            if share < bs.AS_DESCRIBED and not a.get("substitute"):
                why.append(f"description does not fit the title and abstract ({share})")
            if info.get("earliest") and info["earliest"] > k["T"]:
                why.append(f"published after T ({info['earliest']} > {k['T']})")
            pm[pmid]["as_described"] = None if a.get("substitute") else share
        if why:
            out[fid] = {"status": "rejected", "why": why, "pmid": pmid}; n["rejected"] += 1
        else:
            st = "substitute" if a.get("substitute") else "accepted"
            out[fid] = {"status": st, "pmid": pmid, "title": info.get("title"), "earliest": info.get("earliest"), "note": a.get("note", "")}
            n[st] += 1
    (OUT / "pack_21_check.json").write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    pmf.write_text(json.dumps(pm, indent=1, ensure_ascii=False) + "\n")
    gold = bs.gold_answer(original=True)
    by = {(k["sid"], k["pmid_given"]): out[fid] for fid, k in key.items()}
    for sid, g in gold.items():
        papers = []
        for p in g["papers"]:
            fx = by.get((sid, p["pmid"]))
            if fx is None:
                papers.append(p)
            elif fx["status"] in ("accepted", "substitute"):
                papers.append({**p, "pmid": fx["pmid"], "pmid_was": p["pmid"], "substitute": fx["status"] == "substitute"})
        g["papers"] = papers
        cp = g["closest_prior_work"]
        fx = by.get((sid, cp.get("pmid")))
        if fx is not None:
            cp["pmid_was"] = cp["pmid"]
            cp["pmid"] = fx["pmid"] if fx["status"] in ("accepted", "substitute") else ""
    (bs.DIR / "pack_18_answer_fixed.json").write_text(json.dumps({"task": "search_gold_v1", "fixed_by": "pack 21", "items": list(gold.values())}, indent=1, ensure_ascii=False) + "\n")
    return n


if __name__ == "__main__":
    print(json.dumps({"build": build, "apply": apply}[sys.argv[1] if len(sys.argv) > 1 else "build"](), indent=1))

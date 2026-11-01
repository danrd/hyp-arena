"""Outcome labels for DRKS hypotheses (specs/drks-outcomes-2026-11-01.yaml).

    python -m scripts.drks_outcomes plan                 # selection, documents, cost estimate (no model calls)
    ALLOW_PAID=1 python -m scripts.drks_outcomes run     # same labelling as scripts.ctgov_outcomes
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import time
import urllib.request

import yaml

import scripts.ctgov_outcomes as co
from scripts.hypothesis_sources_ctgov import CONDITIONS

KG = co.KG
CAND = KG / "hypothesis_sources" / "drks_candidates.yaml"
INPUTS = KG / "hypothesis_sources" / "drks_outcome_inputs.jsonl"
LABELS = KG / "hypothesis_sources" / "drks_outcomes.yaml"
TOPIC = ('(frailty[tiab] OR sarcopenia[tiab] OR "frail elderly"[MeSH] OR "healthy aging"[tiab] OR "healthy ageing"[tiab] '
         'OR "Aging"[MeSH Major Topic] OR "Sarcopenia"[MeSH])')


def _text(h: str) -> str:
    t = re.sub(r"<script.*?</script>", "", h, flags=re.S)
    t = html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " | ", t)))
    return re.sub(r"(\| )+", "| ", t)


def _field(t: str, a: str, b: str) -> str:
    m = re.search(re.escape(a) + r"\s*\|?(.*?)\|\s*" + b, t)
    return m.group(1).strip(" |") if m else ""


def record(did: str) -> dict:
    t = _text(urllib.request.urlopen(f"https://drks.de/search/en/trial/{did}", timeout=60).read().decode())
    cond = _field(t, "Health condition or problem studied", "Healthy volunteers")
    return {"source_id": did, "source_url": f"https://drks.de/search/en/trial/{did}",
            "written_on": _field(t, "Date of registration in DRKS:", "Last update"),
            "registration_type": _field(t, "Registration type:", "Acronym"), "study_type": _field(t, "Study type:", "Mechanism"),
            "status": _field(t, "Recruitment Status:", "Reason"), "conditions": cond,
            "title": _field(t, "Scientific title", "Brief summary in lay language") or did,
            "summary": _field(t, "Brief summary in lay language", "Brief summary in scientific language") + "\n" +
                       _field(t, "Brief summary in scientific language", "Health condition"),
            "arms": _field(t, "Interventions, Observational Groups", "Endpoints"),
            "primary_outcome": _field(t, "Primary outcome:", "Secondary outcome")}


def aging_itself(cond: str) -> bool:
    parts = [p.strip().lower() for p in re.split(r"[,;/|]|\band\b|free text:", cond)]
    return any(p in CONDITIONS for p in parts) or bool(re.search(r"\bR54\b", cond))


def plan() -> dict:
    from hyparena.tools import pubmed
    from hyparena.backtest import _pubdates
    pmids = pubmed.search(f"DRKS[si] AND {TOPIC}", retmax=500)
    recs = pubmed.fetch(pmids)
    by_id: dict[str, list[str]] = {}
    for p in pmids:
        xml = urllib.request.urlopen(f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pubmed&id={p}&retmode=xml", timeout=60).read().decode()
        for a in set(re.findall(r"<AccessionNumber>(DRKS\d{8})</AccessionNumber>", xml)):
            by_id.setdefault(a, []).append(p)
        time.sleep(0.4)
    cands, rows, stats = [], [], {"drks_ids": len(by_id), "kept": 0}
    for did in sorted(by_id):
        r = record(did)
        time.sleep(1)
        ok = (r["study_type"].startswith("Interventional") and r["registration_type"].startswith("Prospective")
              and r["status"].lower().startswith("recruiting complete") and aging_itself(r["conditions"]))
        r["kept"], r["pmids"] = ok, by_id[did]
        cands.append(r)
        if not ok:
            continue
        dates = _pubdates(by_id[did])
        src = []
        for p in by_id[did]:
            a, d = recs.get(p) or {}, dates.get(p, "")
            if not a.get("abstract") or not d or d <= r["written_on"] or pubmed.is_review(a) or \
                    re.search(r"\bprotocol\b|rationale and design|study design", a.get("title", ""), re.I):
                continue
            src.append({"id": f"P{len(src) + 1}", "kind": f"PubMed abstract, PMID {p}, published {d}", "pmid": p, "date": d,
                        "text": (a["title"] + "\n" + a["abstract"])[:co.MAX_CHARS]})
        if src:
            stats["kept"] += 1
            rows.append({"nct": did, "title": r["title"], "interventions": r["arms"][:600],
                         "primary_outcomes": [{"measure": r["primary_outcome"], "description": "", "time_frame": ""}], "sources": src[:co.MAX_PAPERS]})
    CAND.write_text(yaml.safe_dump({"spec": "specs/drks-outcomes-2026-11-01.yaml", "items": cands}, allow_unicode=True, sort_keys=False, width=200))
    INPUTS.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in rows))
    stats["est_usd"] = round(sum(len(json.dumps(x)) + 2500 for x in rows) / 4 / 1e6 * co.PRICE_IN, 4)
    return stats


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("cmd", choices=["plan", "run"])
    if ap.parse_args().cmd == "plan":
        print(json.dumps(plan(), indent=1))
    else:
        if os.environ.get("ALLOW_PAID") != "1":
            raise SystemExit("paid run: set ALLOW_PAID=1")
        co.INPUTS, co.LABELS = INPUTS, LABELS
        print(co.run())


if __name__ == "__main__":
    main()

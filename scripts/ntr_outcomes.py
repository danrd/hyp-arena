"""Outcome labels for NTR hypotheses (specs/ntr-outcomes-2026-11-01.yaml).

    python -m scripts.ntr_outcomes plan
    ALLOW_PAID=1 python -m scripts.ntr_outcomes run
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import time
import urllib.parse
import urllib.request

import yaml

import scripts.ctgov_outcomes as co
from scripts.drks_outcomes import TOPIC
from scripts.hypothesis_sources_ctgov import CONDITIONS

KG = co.KG
CAND = KG / "hypothesis_sources" / "ntr_candidates.yaml"
INPUTS = KG / "hypothesis_sources" / "ntr_outcome_inputs.jsonl"
LABELS = KG / "hypothesis_sources" / "ntr_outcomes.yaml"
SITE = "https://onderzoekmetmensen.nl"


def _get(url: str) -> str:
    return urllib.request.urlopen(url, timeout=60).read().decode()


def _tag(x: str, name: str) -> str:
    m = re.search(rf"<{name}[^>]*>(.*?)</{name}>", x, re.S)
    return html.unescape(re.sub(r"<[^>]+>", " ", m.group(1))).strip() if m else ""


def record(tid: str) -> dict | None:
    nodes = list(dict.fromkeys(re.findall(r'href="/en/trial/(\d+)"', _get(f"{SITE}/en/search?" + urllib.parse.urlencode({"trial_id": tid})))))
    x = node = None
    for n in nodes[:10]:                 # the search may list several records; take the one that carries the id
        y = _get(f"{SITE}/nl/api/v1/trial/{n}")
        if re.search(rf"\b{re.escape(tid)}\b", y.replace("NTR ", "NTR")):
            x, node = y, n
            break
        time.sleep(0.5)
    if x is None:
        return None
    nodes = [node]
    return {"source_id": tid, "node": nodes[0], "source_url": f"{SITE}/en/trial/{nodes[0]}",
            "written_on": _tag(x, "date_registration")[:10], "enrolment_start": _tag(x, "date_enrolment")[:10],
            "study_type": _tag(x, "study_type"), "recruitment_status": _tag(x, "recruitment_status"),
            "conditions": _tag(x, "hc_freetext"), "title": _tag(x, "scientific_title") or _tag(x, "title"),
            "summary": _tag(x, "background") + "\n" + _tag(x, "objective"), "intervention": _tag(x, "intervention"),
            "primary_outcome": _tag(x, "prim_outcome") or _tag(x, "primaryOutcome")}


def aging_itself(cond: str) -> bool:
    return any(p.strip(" .:").lower() in CONDITIONS for p in re.split(r"[,;/|\n]|\band\b", cond))


def plan() -> dict:
    from hyparena.tools import pubmed
    from hyparena.backtest import _pubdates
    pmids = pubmed.search(f'(NTR[si] OR "Netherlands Trial Register"[si]) AND {TOPIC}', retmax=500)
    recs = pubmed.fetch(pmids)
    by_id: dict[str, list[str]] = {}
    for p in pmids:
        xml = _get(f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pubmed&id={p}&retmode=xml")
        for a in set(re.findall(r"<AccessionNumber>((?:NTR|NL) ?\d{3,5})</AccessionNumber>", xml)):
            by_id.setdefault(a.replace(" ", ""), []).append(p)
        time.sleep(0.4)
    cands, rows, stats = [], [], {"ids": len(by_id), "found": 0, "kept": 0}
    for tid in sorted(by_id):
        r = record(tid)
        time.sleep(1)
        if r is None:
            cands.append({"source_id": tid, "kept": False, "why": "record not found by id"})
            continue
        stats["found"] += 1
        ok = (r["study_type"].lower().startswith("interventional") and r["written_on"] and r["enrolment_start"]
              and r["written_on"] <= r["enrolment_start"] and aging_itself(r["conditions"]))
        r["kept"], r["pmids"] = ok, by_id[tid]
        cands.append(r)
        if not ok:
            continue
        dates = _pubdates(by_id[tid])
        src = []
        for p in by_id[tid]:
            a, d = recs.get(p) or {}, dates.get(p, "")
            if not a.get("abstract") or not d or d <= r["written_on"] or pubmed.is_review(a) or \
                    re.search(r"\bprotocol\b|rationale and design|study design", a.get("title", ""), re.I):
                continue
            src.append({"id": f"P{len(src) + 1}", "kind": f"PubMed abstract, PMID {p}, published {d}", "pmid": p, "date": d,
                        "text": (a["title"] + "\n" + a["abstract"])[:co.MAX_CHARS]})
        if src:
            stats["kept"] += 1
            rows.append({"nct": tid, "title": r["title"], "interventions": r["intervention"][:600],
                         "primary_outcomes": [{"measure": r["primary_outcome"], "description": "", "time_frame": ""}], "sources": src[:co.MAX_PAPERS]})
    CAND.write_text(yaml.safe_dump({"spec": "specs/ntr-outcomes-2026-11-01.yaml", "items": cands}, allow_unicode=True, sort_keys=False, width=200))
    INPUTS.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in rows))
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

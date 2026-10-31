"""Outcome labels for ISRCTN hypotheses (specs/isrctn-outcomes-2026-10-31.yaml).

    python -m scripts.isrctn_outcomes plan                 # no model calls: selection, documents, cost estimate
    ALLOW_PAID=1 python -m scripts.isrctn_outcomes run     # same labelling as scripts.ctgov_outcomes, one call per trial

Inputs and labels go to the private repository ($KG_DIR) only (abstracts belong to their publishers).
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import urllib.parse
import urllib.request

import yaml

import scripts.ctgov_outcomes as co

KG = co.KG
CAND = KG / "hypothesis_sources" / "isrctn_candidates.yaml"
INPUTS = KG / "hypothesis_sources" / "isrctn_outcome_inputs.jsonl"
LABELS = KG / "hypothesis_sources" / "isrctn_outcomes.yaml"
TERMS = ["ageing", "aging", "frailty", "sarcopenia", '"healthy ageing"', '"healthy aging"']
API = "https://www.isrctn.com/api/query/format/default"
END_BEFORE = "2026-10-31"


def _tag(t: str, name: str) -> str:
    m = re.search(rf"<{name}[^>]*>(.*?)</{name}>", t, re.S)
    return html.unescape(m.group(1)).strip() if m else ""


def records() -> dict[str, str]:
    out = {}
    for term in TERMS:
        q = urllib.parse.urlencode({"q": f"condition:{term}", "limit": 500})
        x = urllib.request.urlopen(f"{API}?{q}", timeout=120).read().decode()
        for t in re.findall(r"<fullTrial>(.*?)</fullTrial>", x, re.S):
            out[re.search(r'publicIdentifierCanonical="(ISRCTN\d+)"', t).group(1)] = t
    return out


def candidate(iid: str, t: str) -> dict:
    reg = re.search(r'<isrctn dateAssigned="([^"]+)"', t).group(1)[:10]
    end = _tag(t, "overallEndDate")[:10]
    pmids = re.findall(r'outputType="resultsarticle".*?<externalLink url="https?://(?:www\.)?(?:pubmed\.ncbi\.nlm\.nih\.gov|ncbi\.nlm\.nih\.gov/pubmed)/(\d+)', t, re.S)
    prim = [{"measure": html.unescape(_tag(o, "variable")), "description": html.unescape(_tag(o, "method")),
             "time_frame": html.unescape(_tag(o, "timepoints"))}
            for o in re.findall(r"<outcomeMeasure[^>]*>(.*?)</outcomeMeasure>", t, re.S)
            if o in (re.search(r"<primaryOutcomes>(.*?)</primaryOutcomes>", t, re.S) or [None, ""])[1]]
    if not prim and _tag(t, "primaryOutcome"):
        prim = [{"measure": _tag(t, "primaryOutcome"), "description": "", "time_frame": ""}]
    return {"id": f"isrctn-{iid}", "source": "trial_registry", "source_id": iid, "source_url": f"https://www.isrctn.com/{iid}",
            "written_on": reg, "written_on_basis": "ISRCTN registration date (text: current version)",
            "title": _tag(t, "scientificTitle") or _tag(t, "title"),
            "conditions": [html.unescape(_tag(c, "description")) for c in re.findall(r"<condition>(.*?)</condition>", t, re.S)],
            "interventions": [{"type": _tag(i, "interventionType"), "name": _tag(i, "description")[:300]}
                              for i in re.findall(r"<intervention>(.*?)</intervention>", t, re.S)],
            "study_hypothesis": _tag(t, "studyHypothesis"), "summary": _tag(t, "plainEnglishSummary"),
            "primary_outcomes": prim, "overall_end": end, "result_pmids": sorted(set(pmids)),
            "last_updated": re.search(r'lastUpdated="([^"]+)"', t).group(1)[:10]}


def aging_itself(conditions: list[str]) -> bool:
    """One part of a condition description equals a CT.gov CONDITIONS term (split on , ; / and ' and ')."""
    from scripts.hypothesis_sources_ctgov import CONDITIONS
    real = [c for c in conditions if not re.match(r"\s*topic:", c, re.I) and "generic health relevance" not in c.lower()]   # UK portfolio codes
    parts = [p.strip().lower() for c in real for p in re.split(r"[,;/]|\band\b", c)]
    return any(p in CONDITIONS for p in parts)


def select() -> list[dict]:
    out = []
    for iid, t in sorted(records().items()):
        c = candidate(iid, t)
        if not aging_itself(c["conditions"]):
            continue
        if c["overall_end"] and c["overall_end"] < END_BEFORE and c["written_on"] < c["overall_end"] and c["result_pmids"]:
            out.append(c)
    return out


def plan() -> dict:
    from hyparena.tools import pubmed
    cands = select()
    CAND.write_text(yaml.safe_dump({"spec": "specs/isrctn-outcomes-2026-10-31.yaml", "n": len(cands), "items": cands},
                                   allow_unicode=True, sort_keys=False, width=200))
    rows, stats = [], {"candidates": len(cands), "no_document": 0, "kept": 0}
    for c in cands:
        recs = pubmed.fetch(c["result_pmids"])
        from hyparena.backtest import _pubdates
        dates = _pubdates(c["result_pmids"])
        sources = []
        for p in c["result_pmids"]:
            a = recs.get(p) or {}
            d = dates.get(p, "")
            if not a or not a.get("abstract") or not d or d <= c["written_on"] or pubmed.is_review(a) or re.search(r"\bprotocol\b|rationale and design|study design", a.get("title", ""), re.I):
                continue
            sources.append({"id": f"P{len(sources) + 1}", "kind": f"PubMed abstract, PMID {p}, published {d}", "pmid": p, "date": d,
                            "text": (a.get("title", "") + "\n" + a.get("abstract", ""))[:co.MAX_CHARS]})
            if len(sources) >= co.MAX_PAPERS:
                break
        if not sources:
            stats["no_document"] += 1
            continue
        stats["kept"] += 1
        rows.append({"nct": c["source_id"], "title": c["title"], "interventions": "; ".join(i["name"] for i in c["interventions"]),
                     "primary_outcomes": c["primary_outcomes"], "sources": sources})
    INPUTS.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    chars = sum(len(json.dumps(r, ensure_ascii=False)) + 2500 for r in rows)
    stats["est_usd"] = round(chars / 4 / 1e6 * co.PRICE_IN + len(rows) * 150 / 1e6 * co.PRICE_OUT, 3)
    return stats


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("cmd", choices=["plan", "run"])
    a = ap.parse_args()
    if a.cmd == "plan":
        print(json.dumps(plan(), indent=1))
    else:
        if os.environ.get("ALLOW_PAID") != "1":
            raise SystemExit("paid run: set ALLOW_PAID=1")
        co.INPUTS, co.LABELS = INPUTS, LABELS          # the labelling step is shared with CT.gov (same prompt, model, quote rule)
        print(co.run())


if __name__ == "__main__":
    main()

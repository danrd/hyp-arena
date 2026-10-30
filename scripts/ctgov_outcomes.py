"""Outcome labels for the ClinicalTrials.gov hypotheses (specs/ctgov-outcomes-2026-10-30.yaml).

    python -m scripts.ctgov_outcomes plan                  # no model calls: final selection, outcome documents, cost estimate
    ALLOW_PAID=1 python -m scripts.ctgov_outcomes run      # DeepSeek reads the documents, one call per trial; quotes checked by code
    python -m scripts.ctgov_outcomes recheck               # the manual recheck sheet: >= 30% at random (SHA-1 order) and every uncertain label

Selection on top of scripts/hypothesis_sources_ctgov.py: registered before the primary completion date (prospective registration;
retrospective records were written when the data existed), and at least one outcome document: the results posted in the registry
(primary outcome measures and their statistical analyses, rendered as text), or a PubMed abstract published after the primary
completion date (result papers listed by the investigators first, then records carrying the NCT number), without protocols and
reviews. Abstracts belong to their publishers: inputs and labels are written to the private repository ($KG_DIR) only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import urllib.parse
import urllib.request
from pathlib import Path

import yaml

KG = Path(os.environ.get("KG_DIR", "/home/user/longevity-kg"))
CAND = KG / "hypothesis_sources" / "ctgov_candidates.yaml"
INPUTS = KG / "hypothesis_sources" / "ctgov_outcome_inputs.jsonl"
LABELS = KG / "hypothesis_sources" / "ctgov_outcomes.yaml"
SHEET = KG / "recheck" / "ctgov_outcomes_recheck.md"
MAX_PAPERS, MAX_CHARS = 3, 6000
PRICE_IN, PRICE_OUT = 0.15, 0.6          # DeepSeek V4.1 Flash, USD per M tokens (CometAPI catalogue 2026-10-29; x2 in its weekday peak hours)
LABELS_SET = ("positive", "null", "negative", "mixed", "not_applicable", "not_reported")


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip().lower()


def prospective(c: dict) -> bool:
    return bool(c["primary_completion"]) and c["written_on"] < c["primary_completion"]


def posted_results(nct: str) -> str:
    """The primary outcome measures of the posted results with their groups, values and statistical analyses, as text."""
    q = urllib.parse.urlencode({"fields": "resultsSection.outcomeMeasuresModule"})
    d = json.load(urllib.request.urlopen(f"https://clinicaltrials.gov/api/v2/studies/{nct}?{q}", timeout=90))
    out = []
    for m in (d.get("resultsSection") or {}).get("outcomeMeasuresModule", {}).get("outcomeMeasures", []):
        if m.get("type") != "PRIMARY":
            continue
        groups = {g["id"]: g.get("title", g["id"]) for g in m.get("groups", [])}
        out.append(f"Primary outcome: {m.get('title', '')} ({m.get('unitOfMeasure', '')}; {m.get('paramType', '')}; {m.get('timeFrame', '')})")
        for cl in m.get("classes", []):
            for cat in cl.get("categories", []):
                vals = "; ".join(f"{groups.get(x.get('groupId'), x.get('groupId'))}: {x.get('value', '')}"
                                 + (f" ({x.get('spread')})" if x.get("spread") else "") for x in cat.get("measurements", []))
                label = " ".join(t for t in (cl.get("title", ""), cat.get("title", "")) if t)
                out.append(f"  {label + ': ' if label else ''}{vals}")
        for a in m.get("analyses", []) or []:
            gs = ", ".join(groups.get(g, g) for g in a.get("groupIds", []))
            parts = [f"Analysis ({gs})", a.get("statisticalMethod", ""), f"p-value {a['pValue']}" if a.get("pValue") else "",
                     f"{a.get('paramType', '')} {a.get('paramValue', '')}".strip(),
                     f"CI {a.get('ciLowerLimit', '')} to {a.get('ciUpperLimit', '')}" if a.get("ciLowerLimit") else "",
                     a.get("nonInferiorityType", ""), a.get("statisticalComment", ""), a.get("estimateComment", "")]
            out.append("  " + "; ".join(p for p in parts if p))
    return "\n".join(out)[:MAX_CHARS]


def papers(c: dict) -> list[dict]:
    """Abstracts published after the primary completion date: listed result papers first, then [si] records; no protocols or reviews."""
    from hyparena.tools import pubmed
    pmids = list(dict.fromkeys(c.get("result_pmids_listed", []) + c.get("result_pmids_si", [])))
    from hyparena.backtest import _pubdates
    got = pubmed.fetch(pmids) if pmids else {}
    dates = _pubdates(pmids) if pmids else {}          # earliest public date (e-pub, print, PubMed entry); fetch() has none for cached records
    out = []
    for p in pmids:
        a = got.get(p)
        if not a or not a.get("abstract") or p not in dates:
            continue
        a = {**a, "date": dates[p]}
        if a["date"] <= c["primary_completion"][:10] or pubmed.is_review(a):
            continue
        if re.search(r"\bprotocol\b|rationale and design|study design", a["title"], re.I):
            continue
        out.append({"pmid": p, "date": a.get("date", ""), "text": (a["title"] + "\n" + a["abstract"])[:MAX_CHARS]})
        if len(out) >= MAX_PAPERS:
            break
    return out


def plan() -> dict:
    cands = yaml.safe_load(CAND.read_text())["items"]
    stats = {"candidates": len(cands), "retrospective": 0, "no_document": 0, "kept": 0, "with_posted_results": 0, "with_papers": 0}
    rows = []
    for c in cands:
        if not prospective(c):
            stats["retrospective"] += 1
            continue
        sources = []
        if c["results_posted"]:
            txt = posted_results(c["source_id"])
            if txt:
                sources.append({"id": "R", "kind": "ClinicalTrials.gov posted results", "text": txt})
        for i, p in enumerate(papers(c), 1):
            sources.append({"id": f"P{i}", "kind": f"PubMed abstract, PMID {p['pmid']}, published {p['date']}", "pmid": p["pmid"],
                            "date": p["date"], "text": p["text"]})
        if not sources:
            stats["no_document"] += 1
            continue
        stats["kept"] += 1
        stats["with_posted_results"] += any(s["id"] == "R" for s in sources)
        stats["with_papers"] += any(s["id"].startswith("P") for s in sources)
        rows.append({"nct": c["source_id"], "title": c["title"], "interventions": ", ".join(i["name"] for i in c["interventions"]),
                     "primary_outcomes": c["primary_outcomes"], "sources": sources})
    INPUTS.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    chars = sum(len(json.dumps(r, ensure_ascii=False)) + 2500 for r in rows)       # + the instructions of the prompt
    stats["est_tokens_in"] = chars // 4
    stats["est_usd"] = round(stats["est_tokens_in"] / 1e6 * PRICE_IN + len(rows) * 150 / 1e6 * PRICE_OUT, 2)
    return stats


def verify_quote(r: dict, row: dict) -> bool:
    src = next((s for s in row["sources"] if s["id"] == r.get("source")), None)
    return bool(src) and bool(r.get("quote")) and _norm(r["quote"]) in _norm(src["text"])


def run(config: str = "configs/v2-flash.yaml", family: str = "deepseek", max_calls: int = 700) -> dict:
    from hyparena.llm.prompts import render
    from hyparena.llm.providers import build_client
    from hyparena.llm.structured import parse_json
    client, _, _ = build_client(config, max_calls=max_calls)
    rows = [json.loads(l) for l in INPUTS.read_text().splitlines()]
    done = {x["nct"]: x for x in (yaml.safe_load(LABELS.read_text()) or {}).get("items", [])} if LABELS.exists() else {}
    for row in rows:
        if row["nct"] in done:
            continue
        reply = client.call(role="label_trial_outcome", family=family, prompt=render(
            "label_trial_outcome", "v1", nct=row["nct"], title=row["title"], interventions=row["interventions"],
            primary_outcomes=row["primary_outcomes"], sources=row["sources"]))
        r = parse_json(reply.text) or {}
        label = r.get("label") if r.get("label") in LABELS_SET else "unparsed"
        ok = label == "not_reported" or verify_quote(r, row)
        src = next((s for s in row["sources"] if s["id"] == r.get("source")), {})
        done[row["nct"]] = {"nct": row["nct"], "label": label if ok else "quote_failed", "model_label": label,
                            "source": r.get("source", ""), "pmid_or_url": src.get("pmid") and f"PMID:{src['pmid']}" or
                            (f"https://clinicaltrials.gov/study/{row['nct']}?tab=results" if src else ""),
                            "published_on": src.get("date", ""), "quote": r.get("quote", ""), "note": r.get("note", ""),
                            "model": reply.model_id, "tokens_in": reply.tokens_in, "tokens_out": reply.tokens_out, "error": reply.error}
        LABELS.write_text(yaml.safe_dump({"items": list(done.values())}, allow_unicode=True, sort_keys=False, width=200))
    from collections import Counter
    return dict(Counter(x["label"] for x in done.values()))


def recheck(share: float = 0.30) -> int:
    items = yaml.safe_load(LABELS.read_text())["items"]
    rows = {json.loads(l)["nct"]: json.loads(l) for l in INPUTS.read_text().splitlines()}
    order = sorted(items, key=lambda x: hashlib.sha1(x["nct"].encode()).hexdigest())
    k = -(-int(share * 100) * len(items) // 100)
    pick = order[:k] + [x for x in order[k:] if x["note"] or x["label"] in ("mixed", "quote_failed", "unparsed")]
    SHEET.parent.mkdir(parents=True, exist_ok=True)
    out = [f"# Manual recheck of the ClinicalTrials.gov outcome labels ({len(pick)} of {len(items)}: {k} at random by SHA-1 of the NCT number,"
           " plus every label with a note or mixed/quote_failed/unparsed)", "", "Fill `agree` (yes / no) and `correct label` for each.", ""]
    for x in pick:
        row = rows[x["nct"]]
        out += [f"## {x['nct']} — model: {x['label']} (source {x['source']})", f"Primary outcome(s): " +
                "; ".join(o["measure"] for o in row["primary_outcomes"]), f"Quote: {x['quote']}", f"Note: {x['note']}",
                "agree: · correct label: ", ""]
    SHEET.write_text("\n".join(out))
    return len(pick)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("cmd", choices=["plan", "run", "recheck"])
    a = ap.parse_args()
    if a.cmd == "plan":
        print(json.dumps(plan(), indent=1))
    elif a.cmd == "run":
        if os.environ.get("ALLOW_PAID") != "1":
            raise SystemExit("paid run: set ALLOW_PAID=1")
        print(run())
    else:
        print(recheck(), "items in", SHEET)


if __name__ == "__main__":
    main()

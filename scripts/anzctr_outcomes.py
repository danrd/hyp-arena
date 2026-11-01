"""Outcome labels for ANZCTR hypotheses (specs/anzctr-outcomes-2026-11-01.yaml), from record pages saved by the user (MHTML).

    python -m scripts.anzctr_outcomes plan
    ALLOW_PAID=1 python -m scripts.anzctr_outcomes run
"""
from __future__ import annotations

import argparse
import email
import html
import json
import os
import re
import time
import urllib.request
from datetime import datetime

import yaml

import scripts.ctgov_outcomes as co
from scripts.drks_outcomes import TOPIC
from scripts.hypothesis_sources_ctgov import CONDITIONS

KG = co.KG
PAGES = KG / "hypothesis_sources" / "anzctr_pages"
CAND = KG / "hypothesis_sources" / "anzctr_candidates.yaml"
INPUTS = KG / "hypothesis_sources" / "anzctr_outcome_inputs.jsonl"
LABELS = KG / "hypothesis_sources" / "anzctr_outcomes.yaml"


def _text(path) -> str:
    m = email.message_from_binary_file(open(path, "rb"))
    h = next(p.get_payload(decode=True).decode("utf-8", "ignore") for p in m.walk() if p.get_content_type() == "text/html")
    t = re.sub(r"<script.*?</script>|<style.*?</style>", "", h, flags=re.S)
    t = html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " | ", t)))
    return re.sub(r"(\| )+", "| ", t)


def _f(t: str, a: str, b: str) -> str:
    m = re.search(re.escape(a) + r"\s*\|?(.*?)\|\s*" + re.escape(b), t)
    return re.sub(r"\| \d+ \| 0 \||Query!|\|", " ", m.group(1)).strip() if m else ""


def _d(s: str) -> str:
    m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", s)
    return datetime(int(m.group(3)), int(m.group(2)), int(m.group(1))).strftime("%Y-%m-%d") if m else ""


def record(path) -> dict:
    t = _text(path)
    actrn = (re.search(r"ACTRN\d{14}", t) or [""])[0]
    cond_raw = (re.search(r"Health condition\(s\) studied:\s*\|(.*?)\|\s*Condition category", t) or [None, ""])[1]
    conds = [c.strip() for c in re.split(r"\| \d+ \| 0 \| Query! \||\| Query!", cond_raw) if c.strip(" |")]
    return {"source_id": actrn, "file": path.name, "written_on": _d(_f(t, "Date registered", "Date last updated")),
            "registration_type": _f(t, "Type of registration", "Titles & IDs"), "study_type": _f(t, "Study type", "Description of"),
            "status": _f(t, "Recruitment status", "Data analysis") or _f(t, "Recruitment status", "Date of first"),
            "conditions": [re.sub(r"(\s*\|\s*\d+)+(\s*\|\s*0)*\s*$", "", c).strip(" |") for c in conds],
            "title": _f(t, "Scientific title", "Secondary ID") or _f(t, "Public title", "Scientific title"),
            "summary": _f(t, "Brief summary", "Trial website"),
            "intervention": _f(t, "Description of the intervention or exposure", "Intervention code")[:800],
            "primary_outcome": _f(t, "Primary outcome [1]", "Assessment method [1]")}


def aging_itself(conds: list[str]) -> bool:
    return any(p.strip(" .:").lower() in CONDITIONS for c in conds for p in re.split(r"[,;/\n]|\band\b", c))


def plan() -> dict:
    from hyparena.tools import pubmed
    from hyparena.backtest import _pubdates
    recs_all = {}
    for path in sorted(PAGES.iterdir()):
        r = record(path)
        if r["source_id"] and r["source_id"] not in recs_all:
            recs_all[r["source_id"]] = r
    cands, rows, stats = [], [], {"files": len(list(PAGES.iterdir())), "unique_ids": len(recs_all), "kept": 0}
    for aid, r in sorted(recs_all.items()):
        ok = (r["study_type"].lower().startswith("interventional") and r["registration_type"].lower().startswith("prospective")
              and not r["status"].lower().startswith(("recruiting", "not yet recruiting")) and aging_itself(r["conditions"]))
        r["kept"] = ok
        cands.append(r)
        if not ok:
            continue
        pmids = pubmed.search(f"{aid}[si]", retmax=20)
        time.sleep(1)
        recs, dates = pubmed.fetch(pmids), _pubdates(pmids)
        src = []
        for p in pmids:
            a, d = recs.get(p) or {}, dates.get(p, "")
            if not a.get("abstract") or not d or d <= r["written_on"] or pubmed.is_review(a) or \
                    re.search(r"\bprotocol\b|rationale and design|study design", a.get("title", ""), re.I):
                continue
            src.append({"id": f"P{len(src) + 1}", "kind": f"PubMed abstract, PMID {p}, published {d}", "pmid": p, "date": d,
                        "text": (a["title"] + "\n" + a["abstract"])[:co.MAX_CHARS]})
        r["pmids"] = pmids
        if src:
            stats["kept"] += 1
            rows.append({"nct": aid, "title": r["title"], "interventions": r["intervention"],
                         "primary_outcomes": [{"measure": r["primary_outcome"], "description": "", "time_frame": ""}], "sources": src[:co.MAX_PAPERS]})
    CAND.write_text(yaml.safe_dump({"spec": "specs/anzctr-outcomes-2026-11-01.yaml", "items": cands}, allow_unicode=True, sort_keys=False, width=200))
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

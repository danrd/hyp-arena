"""Outcome labels for UMIN-CTR hypotheses (specs/umin-outcomes-2026-11-01.yaml).

    python -m scripts.umin_outcomes plan
    ALLOW_PAID=1 python -m scripts.umin_outcomes run
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import subprocess
import time
import urllib.request

import yaml

import scripts.ctgov_outcomes as co
from scripts.drks_outcomes import TOPIC
from scripts.hypothesis_sources_ctgov import CONDITIONS

KG = co.KG
CAND = KG / "hypothesis_sources" / "umin_candidates.yaml"
INPUTS = KG / "hypothesis_sources" / "umin_outcome_inputs.jsonl"
LABELS = KG / "hypothesis_sources" / "umin_outcomes.yaml"
BASE = "https://center6.umin.ac.jp/cgi-open-bin/ctr_e/"
NOT_DONE = ("preinitiation", "recruiting", "enrolling by invitation")


def _efetch(p: str) -> str:
    for i in range(6):
        try:
            return urllib.request.urlopen(f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pubmed&id={p}&retmode=xml", timeout=60).read().decode()
        except Exception:
            time.sleep(2 ** i)
    return ""


def _text(h: str) -> str:
    t = html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " | ", h)))
    return re.sub(r"(\| )+", "| ", t)


def _f(t: str, a: str, b: str) -> str:
    m = re.search(re.escape(a) + r"\s*\|(.*?)\|\s*" + re.escape(b), t)
    return m.group(1).strip(" |") if m else ""


def _date(t: str, label: str) -> str:
    m = re.search(re.escape(label) + r" \| (\d{4}) \| Year \| (\d{2}) \| Month \| (\d{2}) \| Day", t)
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else ""


def record(uid: str) -> dict | None:
    uid = uid.replace("UMIN-", "UMIN")
    out = subprocess.run(["curl", "-s", "-m", "60", "-F", f"ctrno={uid}", "-F", "isicdr=1", "-F", "sort=03", BASE + "index.cgi"],
                         capture_output=True, text=True, errors="ignore").stdout          # the site's own public search form
    rec = sorted(set(re.findall(r"recptno=(R\d+)", out)))
    if len(rec) != 1:
        return None
    t = _text(urllib.request.urlopen(BASE + f"ctr_view.cgi?recptno={rec[0]}", timeout=60).read().decode(errors="ignore"))
    return {"source_id": uid, "recptno": rec[0], "source_url": BASE + f"ctr_view.cgi?recptno={rec[0]}",
            "written_on": _date(t, "Registered date"), "trial_start": _date(t, "Anticipated trial start date"),
            "study_type": _f(t, "Study type", "Study design"), "status": _f(t, "Recruitment status", "Unique ID issued by UMIN"),
            "conditions": _f(t, "Condition | Condition", "Classification by specialty"),
            "title": _f(t, "Official scientific title of the study", "Title of the study (Brief title)"),
            "objective": _f(t, "Narrative objectives1", "Basic objectives2"),
            "interventions": _f(t, "Interventions/Control_1", "Interventions/Control_3"),
            "primary_outcome": _f(t, "Primary outcomes", "Key secondary outcomes")}


def aging_itself(cond: str) -> bool:
    return any(p.strip(" .:").lower() in CONDITIONS for p in re.split(r"[,;/|\n]|\band\b", cond))


def plan() -> dict:
    from hyparena.tools import pubmed
    from hyparena.backtest import _pubdates
    pmids = pubmed.search(f"(UMIN-CTR[si] OR UMIN[si]) AND {TOPIC}", retmax=500)
    recs = pubmed.fetch(pmids)
    by_id: dict[str, list[str]] = {}
    for p in pmids:
        xml = _efetch(p)
        for a in set(re.findall(r"<AccessionNumber>(UMIN-?\d{9})</AccessionNumber>", xml)):
            by_id.setdefault(a.replace("UMIN-", "UMIN"), []).append(p)
        time.sleep(1)
    cands, rows, stats = [], [], {"ids": len(by_id), "found": 0, "kept": 0}
    for uid in sorted(by_id):
        r = record(uid)
        time.sleep(1)
        if r is None:
            cands.append({"source_id": uid, "kept": False, "why": "record not found by id"})
            continue
        stats["found"] += 1
        ok = (r["study_type"].lower().startswith("interventional") and not r["status"].lower().startswith(NOT_DONE)
              and r["written_on"] and r["trial_start"] and r["written_on"] <= r["trial_start"] and aging_itself(r["conditions"]))
        r["kept"], r["pmids"] = ok, by_id[uid]
        cands.append(r)
        if not ok:
            continue
        dates = _pubdates(by_id[uid])
        src = []
        for p in by_id[uid]:
            a, d = recs.get(p) or {}, dates.get(p, "")
            if not a.get("abstract") or not d or d <= r["written_on"] or pubmed.is_review(a) or \
                    re.search(r"\bprotocol\b|rationale and design|study design", a.get("title", ""), re.I):
                continue
            src.append({"id": f"P{len(src) + 1}", "kind": f"PubMed abstract, PMID {p}, published {d}", "pmid": p, "date": d,
                        "text": (a["title"] + "\n" + a["abstract"])[:co.MAX_CHARS]})
        if src:
            stats["kept"] += 1
            rows.append({"nct": uid, "title": r["title"], "interventions": r["interventions"][:600],
                         "primary_outcomes": [{"measure": r["primary_outcome"], "description": "", "time_frame": ""}], "sources": src[:co.MAX_PAPERS]})
    CAND.write_text(yaml.safe_dump({"spec": "specs/umin-outcomes-2026-11-01.yaml", "items": cands}, allow_unicode=True, sort_keys=False, width=200))
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

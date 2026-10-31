"""Dated, human-written hypotheses from ClinicalTrials.gov: trials on aging itself, with the registered text copied verbatim and the
sources of the later outcome located (no labels here; labelling is a separate, recorded step).

    python -m scripts.hypothesis_sources_ctgov select      # writes $KG_DIR/hypothesis_sources/ctgov_candidates.yaml

Selection (fixed 2026-10-30, before any outcome was read): interventional studies, overall status COMPLETED, first posted
2000-01-01 to 2022-12-31, whose condition list contains aging itself (the whole condition string, case-insensitive, one of
CONDITIONS). The registry text is the current version: the record history (first version) is not reachable through the public API
(403). The flag `text_after_completion` (record updated after the primary completion date) turned out uninformative: 1083 of
1085 records are updated after completion, if only to set the status; how far the text itself changed is still unknown. Outcome sources, in order: results posted in the registry; publications the
investigators listed as results (referencesModule, type RESULT); PubMed records that carry the NCT number ([si]); a source counts
only if it was published after the primary completion date (checked when labelling).
"""
from __future__ import annotations

import argparse
import json
import os
import urllib.parse
import urllib.request
from pathlib import Path

import yaml

BASE = "https://clinicaltrials.gov/api/v2/studies"
# Batch (env CTGOV_BATCH): "" = first posted 2000-2022 (the main set); "2023" = first posted 2023-01-01 to 2026-10-31
# (extension decided 2026-10-31: results mostly after the training cutoffs of the models used). Files get the suffix _2023.
BATCH = os.environ.get("CTGOV_BATCH", "")
FIRST_FROM, FIRST_TO = ("2023-01-01", "2026-10-31") if BATCH == "2023" else ("2000-01-01", "2022-12-31")
SUFFIX = f"_{BATCH}" if BATCH else ""
CONDITIONS = {"aging", "ageing", "healthy aging", "healthy ageing", "frailty", "frail elderly", "frailty syndrome", "sarcopenia",
              "longevity", "senescence", "biological aging", "inflammaging"}
KG = Path(os.environ.get("KG_DIR", "/home/user/longevity-kg"))


def _get(url: str) -> dict:
    return json.load(urllib.request.urlopen(url, timeout=90))


def studies() -> list[dict]:
    q = " OR ".join(f'"{c}"' for c in sorted(CONDITIONS))
    params = {"query.cond": q, "filter.overallStatus": "COMPLETED", "aggFilters": "studyType:int", "pageSize": 200, "format": "json"}
    out, tok = [], None
    while True:
        p = dict(params, **({"pageToken": tok} if tok else {}))
        d = _get(BASE + "?" + urllib.parse.urlencode(p))
        out += d.get("studies", [])
        tok = d.get("nextPageToken")
        if not tok:
            return out


def _date(status: dict, key: str) -> str:
    """A date of the record's statusModule (YYYY-MM-DD, or YYYY-MM when the registry gives only the month)."""
    return (status.get(key) or {}).get("date", "")


def pubmed_si(nct: str) -> list[str]:
    """PubMed records that carry the NCT number in the secondary-identifier field (rate-limited client); publication dates are checked
    against the primary completion date at the labelling step."""
    from hyparena.tools import pubmed
    return pubmed.search(f"{nct}[si]", retmax=20)


def candidate(st: dict) -> dict | None:
    ps = st["protocolSection"]
    conds = [c.strip().lower() for c in (ps.get("conditionsModule") or {}).get("conditions", [])]
    if not any(c in CONDITIONS for c in conds):
        return None
    status = ps.get("statusModule") or {}
    first = _date(status, "studyFirstPostDateStruct")
    if not (FIRST_FROM <= first <= FIRST_TO):
        return None
    nct = ps["identificationModule"]["nctId"]
    desc = ps.get("descriptionModule") or {}
    prim = (ps.get("outcomesModule") or {}).get("primaryOutcomes", [])
    completion = _date(status, "primaryCompletionDateStruct") or _date(status, "completionDateStruct")
    refs = [r for r in (ps.get("referencesModule") or {}).get("references", []) if r.get("type") == "RESULT" and r.get("pmid")]
    return {
        "id": f"ctgov-{nct}", "source": "trial_registry", "source_id": nct, "source_url": f"https://clinicaltrials.gov/study/{nct}",
        "written_on": first, "written_on_basis": "registry first posted (text: current version)",
        "authors": ((ps.get("sponsorCollaboratorsModule") or {}).get("leadSponsor") or {}).get("name", ""),
        "title": ps["identificationModule"].get("officialTitle") or ps["identificationModule"].get("briefTitle", ""),
        "conditions": (ps.get("conditionsModule") or {}).get("conditions", []),
        "interventions": [{"type": i.get("type"), "name": i.get("name")} for i in (ps.get("armsInterventionsModule") or {}).get("interventions", [])],
        "brief_summary": desc.get("briefSummary", ""), "detailed_description": desc.get("detailedDescription", ""),
        "primary_outcomes": [{"measure": o.get("measure", ""), "description": o.get("description", ""), "time_frame": o.get("timeFrame", "")} for o in prim],
        "primary_completion": completion, "last_update_posted": _date(status, "lastUpdatePostDateStruct"),
        "text_after_completion": bool(completion and _date(status, "lastUpdatePostDateStruct") > completion),
        "results_posted": bool(st.get("hasResults")), "results_first_posted": _date(status, "resultsFirstPostDateStruct"),
        "result_pmids_listed": [r["pmid"] for r in refs],
    }


def select() -> list[dict]:
    out = []
    for st in studies():
        c = candidate(st)
        if c is None:
            continue
        if not c["results_posted"] and not c["result_pmids_listed"]:
            c["result_pmids_si"] = pubmed_si(c["source_id"])
        out.append(c)
    return sorted(out, key=lambda c: c["source_id"])


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("cmd", choices=["select"])
    ap.parse_args()
    items = select()
    path = KG / "hypothesis_sources" / f"ctgov_candidates{SUFFIX}.yaml"
    head = {"selection": __doc__.split("Selection", 1)[1].strip(), "n": len(items)}
    path.write_text(yaml.safe_dump({**head, "items": items}, allow_unicode=True, sort_keys=False, width=200))
    has = lambda c: c["results_posted"] or c["result_pmids_listed"] or c.get("result_pmids_si")
    print(path, len(items), "trials; with an outcome source:", sum(1 for c in items if has(c)),
          "| results posted:", sum(c["results_posted"] for c in items), "| listed result papers:", sum(bool(c["result_pmids_listed"]) for c in items),
          "| only PubMed [si]:", sum(1 for c in items if not c["results_posted"] and not c["result_pmids_listed"] and c.get("result_pmids_si")),
          "| text updated after completion:", sum(c["text_after_completion"] for c in items))


if __name__ == "__main__":
    main()

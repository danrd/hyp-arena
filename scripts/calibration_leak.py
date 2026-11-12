"""Leak check of the calibration texts (74 trials with known outcomes). Free, no model call.

    python -m scripts.calibration_leak     # longevity-kg/hypothesis_sources/calibration/leak_check.json

T of a calibration trial is min(registry first posted, primary completion) (scripts/calibration.py `as_of`), while the text
the pipeline reads is the CURRENT version of the record (the registry's history API refuses automated access). So a text
can carry knowledge from after T. Two kinds of evidence, both from data we already have or the registry's current record:

dates (ClinicalTrials.gov API v2 for NCT ids; candidate files for ISRCTN, UMIN, NTR):
  after_completion  the record was first posted after the primary completion: T is the completion date, the whole text was
                    written after the data were collected (often after the analysis)
  after_start       first posted after the start, before completion (retrospective registration; text written mid-trial)
  updated_after_T   the current version was posted after T (its text may differ from the one at T; not checkable)
  results_before_update  results were posted in the registry before the current version
text (the text as the pipeline reads it; the matched phrase is kept):
  title_result      the title states the result ("X Increases Muscle Mass", "Y Does Not Promote ..."); an aim ("to improve")
                    is not one
  results_section   the text has its own "Results:" or "Conclusion:" part
  result_phrase     a result-like phrase anywhere ("significantly improved", "was associated with", "p < 0.05"): only a
                    candidate list for reading, most are about earlier studies or the hypothesis ("will significantly
                    improve"); not graded
  retrospective     the conduct is told in the past: "were randomized", "examined whether", "was carried out", ...
Grade: outcome_in_text = title_result or results_section (the label can be read off the text); written_after_data =
after_completion; retrospective = after_start or retrospective wording or results before the current version;
updated = updated after T only; none.
"""
from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

import yaml

KG = Path(__file__).resolve().parents[2] / "longevity-kg"
HS = KG / "hypothesis_sources"
OUT = HS / "calibration" / "leak_check.json"
GRADES = ("outcome_in_text", "written_after_data", "retrospective", "updated", "none")
API = "https://clinicaltrials.gov/api/v2/studies"

RESULT = [r"\b(?:was|were) (?:significantly )?(?:associated|correlated) with\b",
          r"\bsignificant(?:ly)? (?:improv|increas|decreas|reduc|higher|lower|greater|better|differen)\w*",
          r"\b(?:improved|increased|decreased|reduced) significantly\b",
          r"\bp ?[<=≤] ?0?\.\d+", r"\b95 ?% ?(?:CI|confidence interval)\b",
          r"\b(?:we|the study|this study|the trial|results?) (?:found|showed|demonstrated|revealed|indicated|suggest(?:ed)?)\b",
          r"\b(?:showed|demonstrated|revealed) (?:a |an |that |no |significant )",
          r"\bno significant (?:difference|change|effect|improvement)s?\b",
          r"\b(?:led|resulted) (?:to|in) (?:a |an )?(?:significant|greater|improv|reduc|increas|decreas)\w*"]
TITLE_RESULT = (r"(?<!to )(?<!To )\b(?:improves|increases|decreases|reduces|enhances|prevents|attenuates|reverses|restores|"
                r"promotes|is associated with|are associated with|does not|did not|do not)\b")
SECTION = r"\b(?:Results?|Conclusions?)\s*:\s"
RETRO = [r"\b(?:were|was) (?:randomi[sz]ed|allocated|assigned|enrolled|recruited|included|carried out|conducted|performed|"
         r"collected|analy[sz]ed|followed|measured|assessed|evaluated|delivered)\b",
         r"\bexamined whether\b", r"\b(?:this|the) (?:study|trial|evaluation) (?:examined|evaluated|assessed|investigated|compared|tested)\b",
         r"\bparticipants (?:completed|received|attended)\b"]


def _phrases(text: str, pats: list[str]) -> list[str]:
    out = []
    for p in pats:
        for m in re.finditer(p, text, flags=re.I):
            a, b = max(0, m.start() - 60), min(len(text), m.end() + 60)
            out.append(text[a:b].replace("\n", " "))
    return out


def _day(s: str | None) -> str:
    s = str(s or "")[:10]
    return s + "-01" if len(s) == 7 else s


def _ctgov(ids: list[str]) -> dict:
    out = {}
    for k in range(0, len(ids), 50):
        q = urllib.parse.urlencode({"filter.ids": ",".join(ids[k:k + 50]), "pageSize": 100,
                                    "fields": "NCTId,StartDate,PrimaryCompletionDate,StudyFirstPostDate,LastUpdatePostDate,ResultsFirstPostDate"})
        for s in json.loads(urllib.request.urlopen(f"{API}?{q}", timeout=60).read())["studies"]:
            m = s["protocolSection"]["statusModule"]
            out[s["protocolSection"]["identificationModule"]["nctId"]] = {
                "registered": _day(m.get("studyFirstPostDateStruct", {}).get("date")),
                "start": _day(m.get("startDateStruct", {}).get("date")),
                "completion": _day(m.get("primaryCompletionDateStruct", {}).get("date")),
                "last_update": _day(m.get("lastUpdatePostDateStruct", {}).get("date")),
                "results_posted": _day(s.get("resultsSection") and "" or m.get("resultsFirstPostDateStruct", {}).get("date"))}
    return out


def _others() -> dict:
    out = {}
    for f, reg, start, end, upd in (("isrctn_candidates.yaml", "written_on", None, "overall_end", "last_updated"),
                                    ("umin_candidates.yaml", "written_on", "trial_start", None, None),
                                    ("ntr_candidates.yaml", "written_on", "enrolment_start", None, None)):
        d = yaml.safe_load((HS / f).read_text())
        for c in (d["items"] if isinstance(d, dict) else d):
            out[c["source_id"]] = {"registered": _day(c.get(reg)), "start": _day(c.get(start)) if start else "",
                                   "completion": _day(c.get(end)) if end else "", "last_update": _day(c.get(upd)) if upd else "",
                                   "results_posted": ""}
    return out


def check() -> dict:
    rows = [json.loads(l) for l in (KG / "hypothesis_db" / "rows.jsonl").read_text().splitlines()]
    cal = [r for r in rows if "calibration-74" in r["sets"]]
    dates = _ctgov([r["source_id"] for r in cal if r["source"] == "ctgov"]) | _others()
    pack18 = {v["unit"]: k for k, v in json.loads((KG / "reviews" / "argon-2026-11-12" / "pack_18_key.json").read_text()).items()}
    units = []
    for r in cal:
        d, T = dates.get(r["source_id"], {}), r["T"]
        flags = []
        if d.get("registered") and d.get("completion") and d["registered"] > d["completion"]:
            flags.append("after_completion")
        elif d.get("registered") and d.get("start") and d["registered"] > d["start"]:
            flags.append("after_start")
        if d.get("last_update") and d["last_update"] > T:
            flags.append("updated_after_T")
        if d.get("results_posted") and d.get("last_update") and d["results_posted"] <= d["last_update"]:
            flags.append("results_before_update")
        res, retro = _phrases(r["text"], RESULT), _phrases(r["text"], RETRO)
        title = next((l[7:] for l in r["text"].splitlines() if l.startswith("Title: ")), "")
        if re.search(TITLE_RESULT, title, flags=re.I):
            flags.append("title_result")
        if re.search(SECTION, r["text"]):
            flags.append("results_section")
        if res:
            flags.append("result_phrase")
        if retro:
            flags.append("retrospective")
        fs = set(flags)
        grade = ("outcome_in_text" if {"title_result", "results_section"} & fs else
                 "written_after_data" if "after_completion" in fs else
                 "retrospective" if {"after_start", "retrospective", "results_before_update"} & fs else
                 "updated" if "updated_after_T" in fs else "none")
        units.append({"short": r["short"], "unit": r["source_id"], "source": r["source"], "T": T, "label": (r.get("outcome") or {}).get("label"),
                      "pack18": pack18.get(r["source_id"]), "dates": d, "flags": flags, "grade": grade,
                      "title": title,
                      "result_phrases": res[:4], "retrospective_phrases": retro[:3]})
    summ = {"units": len(units), "grade": dict(Counter(u["grade"] for u in units)),
            "flags": dict(Counter(f for u in units for f in u["flags"])),
            "grade_by_label": {g: dict(Counter(u["label"] for u in units if u["grade"] == g)) for g in GRADES},
            "pack18_grade": dict(Counter(u["grade"] for u in units if u["pack18"])),
            "no_dates": [u["unit"] for u in units if not u["dates"]]}
    OUT.write_text(json.dumps({"summary": summ, "units": units}, indent=1, ensure_ascii=False) + "\n")
    return summ


if __name__ == "__main__":
    print(json.dumps(check(), indent=1, ensure_ascii=False))

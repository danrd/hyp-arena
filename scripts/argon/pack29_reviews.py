"""Argon pack 29 (specs/whole-system/review-gold-2026-11-17.yaml): a gold of links labelled by later systematic reviews.
Code draws 60 Cochrane reviews on older adults (2021-2025) from a fixed PubMed query; Argon gives for each the link
(intervention -> main outcome -> population), the pooled result as a label, its GRADE certainty and the years of the studies
that the pooled estimate contains; code checks it and sets T from the study years.

    python -m scripts.argon.pack29_reviews build    # free: longevity-kg/reviews/argon-2026-11-17/pack_29_{1,2,3}_task.json
    python -m scripts.argon.pack29_reviews check    # free, after the answers: PMIDs, titles, quotes, study years, T
"""
from __future__ import annotations

import argparse
import json
import math
import random
from pathlib import Path

KG = Path(__file__).resolve().parents[2].parent / "longevity-kg"
DIR = KG / "reviews" / "argon-2026-11-17"
QUERY = ('"Cochrane Database Syst Rev"[ta] AND 2021/01/01:2025/12/31[dp] AND hasabstract AND ("older adults"[tiab] OR '
         '"older people"[tiab] OR "older persons"[tiab] OR elderly[tiab] OR frail*[tiab] OR "aged 65"[tiab] OR "aged 60"[tiab] OR '
         '"Aged"[mh] OR older[ti] OR "later life"[ti]) NOT (withdrawn[ti] OR "diagnostic test accuracy"[tiab] OR '
         '"diagnostic accuracy"[ti] OR prognos*[ti] OR qualitative[ti] OR overview[ti] OR "Cochrane reviews"[ti])')
N, SEED, PARTS = 60, 20261117, 3
LABELS = ("benefit", "no_effect", "harm")
EXCLUDE = ("not_intervention", "population_not_ageing", "no_pooled_estimate", "included_studies_not_accessible", "other")

INSTRUCTIONS = """You are building a gold standard for a system that judges the state of evidence on a link "intervention ->
outcome -> population". Each item is a Cochrane systematic review (PMID, title, year). For each review read its abstract and,
for the list of included studies, an OPENLY accessible version of the review (the Cochrane Library or PubMed Central). Do
not use any version behind a paywall or a login; if no open version shows the included studies, exclude the review with
reason included_studies_not_accessible.

For each review:
1. include or exclude. Include only a review of an intervention (drug, supplement, exercise, nutrition, behavioural,
   device, procedure, organisation of care) in older adults or in an age-related condition, with a pooled estimate for its
   main outcome. Otherwise exclude with one reason: not_intervention | population_not_ageing | no_pooled_estimate |
   included_studies_not_accessible | other (say what).
2. main comparison: the FIRST comparison the abstract reports results for. Main outcome: the FIRST primary outcome of that
   comparison that has a pooled estimate in the abstract.
3. link, in the review's own words: intervention, comparator, main outcome, population; and the kind of intervention:
   drug | supplement | exercise | nutrition | behavioural | device | procedure | organisation_of_care | other.
4. label of the main outcome: benefit (the pooled estimate favours the intervention and its 95% interval excludes no
   effect; for an outcome where less is better, such as falls, a reduction) | no_effect (the interval includes no effect) |
   harm (favours the comparator, the interval excludes no effect). Give the pooled estimate as written (e.g. "RR 0.77, 95%
   CI 0.67 to 0.89; 12 studies, 3500 participants") and result_quote: the sentence of the ABSTRACT that gives it, copied
   exactly, character for character.
5. certainty: the GRADE certainty of that outcome as the abstract states it: high | moderate | low | very_low | not_stated,
   with certainty_quote (the abstract's sentence, copied exactly; empty if not stated). conclusion_quote: the first sentence
   of the abstract's "Authors' conclusions", copied exactly.
6. studies: the included studies that contribute to the main outcome's pooled estimate (from the forest plot or the
   analysis table; contributes_known: true). If the review does not show which, list all included studies of the main
   comparison and set contributes_known: false. Per study: its name as the review gives it (e.g. "Smith 2015"), the year
   of its FIRST publication, and its PMID if you can find it (a PMID you are not sure of is left empty). If there are more
   than 40 such studies, give studies_per_year instead (e.g. {"2009": 3, "2012": 5}) and an empty list.

Rules: work from the review itself, not from memory; never guess a PMID; quotes copied exactly from the abstract (one
passage); a review that you cannot open is excluded, not labelled from its abstract alone.

Answer with one JSON object, nothing else:
{"task": "pack_29", "part": 0, "reviews": [{"pmid": "", "include": true, "exclude_reason": "", "exclude_note": "",
  "main_comparison": "", "intervention": "", "comparator": "", "outcome": "", "population": "", "intervention_kind": "",
  "label": "benefit | no_effect | harm", "pooled_estimate": "", "result_quote": "", "certainty": "", "certainty_quote": "",
  "conclusion_quote": "", "contributes_known": true, "studies": [{"name": "", "year": 0, "pmid": ""}], "studies_per_year": {},
  "source_used": "Cochrane Library | PMC (URL)"}]}"""

COVER = ("Это задание на разметку систематических обзоров, часть {part} из трёх, части независимы. По каждому обзору Cochrane "
         "реши, подходит ли он, выпиши звено «вмешательство → главный исход → популяция», сводный результат по главному "
         "исходу с дословной фразой из аннотации, уверенность GRADE и годы испытаний, вошедших в этот сводный результат. "
         "Пользуйся только открытыми версиями обзоров (Cochrane Library или PMC). Ответ — один JSON-объект в формате из "
         "конца инструкции, без текста вокруг.")


def _pool() -> list[str]:
    from hyparena.tools import pubmed
    r = pubmed._get("esearch.fcgi", {"db": "pubmed", "term": QUERY, "retmax": 1000, "retmode": "json"}).json()["esearchresult"]
    return sorted(r["idlist"], key=int)


def build() -> dict:
    from hyparena.tools import pubmed
    pool = _pool()
    pick = random.Random(SEED).sample(pool, N)
    meta = pubmed.fetch(pick)
    DIR.mkdir(parents=True, exist_ok=True)
    items = [{"pmid": p, "title": meta[p]["title"], "year": meta[p]["year"]} for p in pick]
    size = math.ceil(N / PARTS)
    for i in range(PARTS):
        part = items[i * size:(i + 1) * size]
        task = {"task": "pack_29", "part": i + 1, "instructions": INSTRUCTIONS, "reviews": part}
        (DIR / f"pack_29_{i + 1}_task.json").write_text(json.dumps(task, indent=1, ensure_ascii=False) + "\n")
    (DIR / "pack_29_sample.json").write_text(json.dumps({"query": QUERY, "pool": len(pool), "seed": SEED, "pmids": pick},
                                                        indent=1) + "\n")
    return {"pool": len(pool), "sampled": len(pick), "parts": PARTS}


def t_of(years: list[int]) -> tuple[int | None, bool]:
    """(Y, usable): Y the earliest year by which at least half of the studies were published; usable when at least one
    study is on or before Y and at least one after it."""
    ys = sorted(y for y in years if y)
    if not ys:
        return None, False
    Y = next(y for y in ys if sum(v <= y for v in ys) >= len(ys) / 2)
    return Y, any(v <= Y for v in ys) and any(v > Y for v in ys)


def check() -> dict:
    from hyparena.tools import pubmed
    from scripts.argon.generation_tasks import quote_found
    sample = json.loads((DIR / "pack_29_sample.json").read_text())["pmids"]
    ans = {}
    for i in range(1, PARTS + 1):
        f = DIR / f"pack_29_{i}_answer.json"
        if f.exists():
            ans.update({str(r.get("pmid", "")).strip(): r for r in json.loads(f.read_text()).get("reviews") or []})
    revs = pubmed.fetch([p for p in sample if p in ans])
    study_pmids = sorted({str(s.get("pmid") or "").strip() for r in ans.values() for s in r.get("studies") or []} - {""})
    studies_meta = pubmed.fetch([p for p in study_pmids if p.isdigit()])
    rows, counts = [], {"answered": 0, "included": 0, "usable": 0, "labels": {}, "excluded": {}}
    for p in sample:
        a = ans.get(p)
        if a is None:
            rows.append({"pmid": p, "answered": False})
            continue
        counts["answered"] += 1
        m = revs.get(p, {})
        row = {"pmid": p, "answered": True, "include": bool(a.get("include"))}
        if not a.get("include"):
            reason = a.get("exclude_reason") if a.get("exclude_reason") in EXCLUDE else "invalid_reason"
            counts["excluded"][reason] = counts["excluded"].get(reason, 0) + 1
            rows.append(row | {"exclude_reason": reason})
            continue
        counts["included"] += 1
        row["label"] = a.get("label") if a.get("label") in LABELS else "invalid"
        row["quotes"] = {k: (quote_found(a.get(k, ""), m.get("title", ""), m.get("abstract", "")) if a.get(k) else "empty")
                         for k in ("result_quote", "certainty_quote", "conclusion_quote")}
        years, bad = [], []
        for s in a.get("studies") or []:
            y, sp = s.get("year"), str(s.get("pmid") or "").strip()
            if sp:
                sm = studies_meta.get(sp)
                if not sm:
                    bad.append({"name": s.get("name"), "pmid": sp, "problem": "pmid not found"})
                elif sm.get("year", "").isdigit() and (not isinstance(y, int) or abs(int(sm["year"]) - y) > 1):
                    bad.append({"name": s.get("name"), "pmid": sp, "problem": f"year {y} vs PubMed {sm['year']}"})
                    y = int(sm["year"])
                if sm and sm.get("year", "").isdigit() and m.get("year", "").isdigit() and int(sm["year"]) > int(m["year"]):
                    bad.append({"name": s.get("name"), "pmid": sp, "problem": "after the review"})
            if isinstance(y, int):
                years.append(y)
        for yr, k in (a.get("studies_per_year") or {}).items():
            if str(yr).isdigit():
                years += [int(yr)] * int(k)
        Y, usable = t_of(years)
        row.update({"studies": len(years), "study_problems": bad, "Y": Y, "T": f"{Y}-12-31" if Y else None, "usable": usable,
                    "contributes_known": a.get("contributes_known")})
        if usable and row["label"] in LABELS and row["quotes"]["result_quote"] == "whole":
            counts["usable"] += 1
            counts["labels"][row["label"]] = counts["labels"].get(row["label"], 0) + 1
        rows.append(row)
    counts["pmids_not_in_the_sample"] = sorted(set(ans) - set(sample))
    out = counts | {"rows": rows}
    (DIR / "pack_29_check.json").write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    return {k: v for k, v in out.items() if k != "rows"}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("cmd", choices=["build", "check"])
    print(json.dumps(build() if ap.parse_args().cmd == "build" else check(), indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()

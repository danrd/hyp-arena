"""Argon pack 27 (specs/scoring/effect-phrase-2026-11-15.yaml, argon_pack27): the published grounds for the thresholds by
which code reads the size of an effect from a verbatim phrase (standardised difference, ratios, percent change, a raw
difference with its interval) and for the one line the record weight draws (at least medium against smaller or unknown).

    python -m scripts.argon.pack27_effect_thresholds build      # free
    python -m scripts.argon.pack27_effect_thresholds check      # free, after the answer: PMIDs, titles, quotes
"""
from __future__ import annotations

import argparse
import json

from scripts.common.v34_check import CAL

DIR = CAL.parents[1] / "reviews" / "argon-2026-11-15"

CONTEXT = ("The method reads abstracts of studies of ageing interventions in older adults (exercise and rehabilitation "
           "programmes, nutrition and supplements, drugs, behavioural and care programmes) and in animals. For a finding that "
           "supports a claim, code classes the stated effect as small, medium or large; the weight of the finding uses one "
           "line only: at least medium counts fully, smaller or unknown counts half. On 297 supporting findings of 30 "
           "trials the size could be read in 68: small 45, medium 9, large 14; in 229 the abstract gave no usable size.")

THRESHOLDS = [
    {"id": "T1", "kind": "standardised mean difference (Cohen's d, Hedges' g, SMD)",
     "ours": "small below 0.5, medium 0.5 to 0.8, large from 0.8; the weight's line is 0.5",
     "question": "Cohen offered 0.2 / 0.5 / 0.8 as conventions for behavioural science. What are the EMPIRICAL distributions of effect sizes in the fields above (gerontology, exercise and rehabilitation in older adults, nutrition, pharmacological trials; Cochrane-wide surveys): which values are the median and the upper quartile? Is 0.5 a defensible line for 'at least medium' there, or should it be lower (for example 0.3 or 0.4)?"},
    {"id": "T2", "kind": "ratios (odds ratio, risk ratio, hazard ratio, n-fold)",
     "ours": "small 0.8 to 1.25, medium 1.25 to 2 or 0.5 to 0.8, large from 2 or up to 0.5; the weight's line is 1.25 (0.8); for the weight a ratio is converted as d = ln(OR) x sqrt(3) / pi",
     "question": "What do GRADE and the Cochrane Handbook use as a large and a very large effect for ratios, and as a threshold of an appreciable benefit or harm? Which ratios correspond to d = 0.2, 0.5 and 0.8 (Chinn 2000; Chen, Cohen and Chen 2010 and later work), and how does the answer depend on the baseline risk? Is treating risk ratios and hazard ratios by the odds-ratio conversion defensible? Is 1.25 a defensible line for 'at least medium'?"},
    {"id": "T3", "kind": "relative change in percent",
     "ours": "small below 5%, medium 5% to 20%, large above 20%; the weight's line is 5%; these are working values without a published ground",
     "question": "Is there any published ground for classing a percent change without its variability (per measure: muscle strength, gait speed, bone mineral density, body weight, blood pressure, biomarkers)? Or should a percent change without a standard deviation or an interval be left as 'size unknown'? If thresholds per kind of measure exist, give them."},
    {"id": "T4", "kind": "a raw difference with its 95% confidence interval and n",
     "ours": "SE = (upper - lower) / 3.92; SD = SE x sqrt(n) / 2 between two groups of equal size (SE x sqrt(n) before-after); d = |difference| / SD",
     "question": "Is this conversion the standard one (Cochrane Handbook section and formula)? What are its known errors: unequal groups, small samples (t instead of 1.96), adjusted estimates (ANCOVA, baseline-adjusted differences give a smaller SE and so a larger d), paired designs where the SD of the change is not the SD between people, cluster trials? Which correction is worth applying from an abstract alone?"},
    {"id": "T5", "kind": "minimal clinically important differences of common measures in older adults",
     "ours": "not used; a difference in units without an interval is 'size unknown'",
     "question": "For the Short Physical Performance Battery, gait speed, 6-minute walk distance, timed up and go, chair rise, handgrip strength, MMSE, MoCA, Barthel index and ADL scales: the published minimal clinically important difference and the 'substantial' difference (with the population they were derived in), and what standardised difference each corresponds to (is the MCID nearer 0.2, 0.3 or 0.5 SD: Norman 2003 and later)? Would 'reaches the MCID' be a better line for 'at least medium' than d = 0.5?"},
    {"id": "T6", "kind": "one line or three classes; the unknown size",
     "ours": "three classes are shown, one line is used in the weight; an effect whose size cannot be read weighs like a small one (1/2)",
     "question": "Is there published support for (a) distinguishing medium from large in the confidence a finding deserves, (b) treating a significant effect of unknown size like a small one rather than like an average one, (c) using the size of the effect at all when the finding is already weighed by design and sample size (large effects in small trials shrink on replication)? Which of these do GRADE's rating-up rules and meta-research support?"},
]

INSTRUCTIONS = """You are an expert in evidence-based medicine, biostatistics and research methodology. A method for scoring hypotheses
about ageing interventions classes the SIZE of a published effect by thresholds, listed below with the method's own values.
For each item, find the PUBLISHED GROUNDS for the thresholds:
- methodological standards and handbooks (Cochrane Handbook, GRADE guidelines, CONSORT and similar) - what they say and where;
- empirical studies that MEASURE the quantity asked about (distributions of effect sizes in a field, conversions between
  effect measures, minimal clinically important differences with their derivation, errors of a conversion).

For each item answer:
- sources: up to 6, the most informative first; each a real PubMed paper with its PMID, exact title, first author and year,
  what it shows IN NUMBERS, and one verbatim quote from its abstract that carries the number or the claim; a handbook
  chapter without a PMID may be named with its title, edition and section instead;
- verdict on our value: supported | too_high | too_low | no_evidence | drop (the threshold has no ground and should not be
  used), and a one-sentence reason;
- suggested_value: the thresholds or the rule the sources support, or "keep";
- for T5 also a table: measure, MCID, substantial difference, population, PMID.

Rules: only real papers - a PMID you are not sure of is left out; a quote is copied verbatim from the abstract (one passage);
prefer empirical and meta-research studies to opinion; say plainly when no evidence exists.

Answer with one JSON object, nothing else:
{"task": "pack_27", "items": [{"id": "T1", "sources": [{"pmid": "", "title": "", "first_author": "", "year": 0,
  "shows": "", "quote": "", "kind": "standard | empirical | meta_research | review | other"}],
  "handbook_sections": [{"title": "", "section": ""}], "verdict": "supported | too_high | too_low | no_evidence | drop",
  "reason": "", "suggested_value": "",
  "mcid_table": [{"measure": "", "mcid": "", "substantial": "", "population": "", "pmid": ""}]}], "general_notes": ""}"""


def build() -> dict:
    DIR.mkdir(parents=True, exist_ok=True)
    f = DIR / "pack_27_task.json"
    f.write_text(json.dumps({"task": "pack_27", "written_on": "2026-11-15", "instructions": INSTRUCTIONS, "context": CONTEXT,
                             "items": THRESHOLDS}, indent=1, ensure_ascii=False) + "\n")
    return {"items": len(THRESHOLDS), "kb": round(f.stat().st_size / 1024, 1)}


def check() -> dict:
    from hyparena.tools import pubmed
    from scripts.argon.generation_tasks import quote_found, title_matches
    from scripts.search.bench_search import summaries
    ans = json.loads((DIR / "pack_27_answer.json").read_text())
    srcs = [(i["id"], s) for i in ans.get("items") or [] for s in i.get("sources") or [] if str(s.get("pmid", "")).strip().isdigit()]
    mcid = sorted({str(r.get("pmid", "")).strip() for i in ans.get("items") or [] for r in i.get("mcid_table") or []} - {""})
    cache: dict = {}
    summaries(sorted({str(s["pmid"]).strip() for _, s in srcs} | {p for p in mcid if p.isdigit()}), cache)
    abstracts = pubmed.fetch([p for p, v in cache.items() if v.get("exists")])
    rows = []
    for tid, s in srcs:
        p = str(s["pmid"]).strip()
        meta, a = cache.get(p, {}), abstracts.get(p) or {}
        rows.append({"item": tid, "pmid": p, "exists": meta.get("exists", False),
                     "title_matches": title_matches(s.get("title", ""), meta.get("title", "")) if meta.get("exists") else None,
                     "quote": quote_found(s.get("quote", ""), a.get("title", ""), a.get("abstract", "")) if a else "paper not found"})
    out = {"sources": len(rows), "exist": sum(r["exists"] for r in rows), "title_matches": sum(bool(r["title_matches"]) for r in rows),
           "quotes_verbatim": sum(r["quote"] == "whole" for r in rows),
           "mcid_pmids": len(mcid), "mcid_pmids_exist": sum(cache.get(p, {}).get("exists", False) for p in mcid), "rows": rows}
    (DIR / "pack_27_check.json").write_text(json.dumps(out, indent=1) + "\n")
    return {k: v for k, v in out.items() if k != "rows"}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("cmd", choices=["build", "check"])
    print(json.dumps(build() if ap.parse_args().cmd == "build" else check(), indent=1))


if __name__ == "__main__":
    main()

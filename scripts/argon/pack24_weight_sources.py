"""Argon pack 24 (specs/scoring/weight-sources-2026-11-15.yaml): the published grounds for the factors of a record's weight.
The method weighs each evidence record by GRADE-shaped factors whose numbers are its own (GRADE gives levels, not
multipliers). The pack asks the outside reader for the published evidence on each factor - methodological standards,
meta-epidemiological studies that measure how much a design or feature biases or weakens an estimate - with PMIDs, what
each shows in numbers, and whether our value is supported, too high or too low.

    python -m scripts.argon.pack24_weight_sources build      # free
    python -m scripts.argon.pack24_weight_sources check      # free, after the answer: PMIDs, titles, quotes
"""
from __future__ import annotations

import argparse
import json

from scripts.common.v34_check import CAL

DIR = CAL.parents[1] / "reviews" / "argon-2026-11-15"

FACTORS = [
    {"id": "F1", "factor": "design, outcome link of a claim about humans",
     "ours": "RCT 1; meta-analysis by its GRADE certainty: high or moderate 1, low 1/2, very low 1/4, not stated 1; non-randomised controlled and observational 1/2; animal, cells, review, other 1/4",
     "question": "How much weaker is the evidence of each design than an RCT for the same question? Is a meta-analysis of RCTs stronger than a single large RCT, and does a meta-analysis that does not state its certainty deserve the weight of an RCT? What multipliers do the published comparisons support?"},
    {"id": "F2", "factor": "design, a step of the mechanism before the outcome (preclinical scale)",
     "ours": "animal 1, review 2/3, cells 1/3 (and in a human claim before the outcome: rct 1, meta-analysis 6/7, non-randomised 5/7, review 4/7, observational 3/7, animal 2/7, cells 1/7)",
     "question": "How well do animal and cell findings predict the human effect (translation rates, concordance studies)? Is an animal study rightly placed above a review and cells for a mechanistic step?"},
    {"id": "F3", "factor": "precision of a record that supports the claim",
     "ours": "min(1, ln n / ln 300), at least 1/4 (n 10: 0.40; 30: 0.60; 100: 0.81; 300 and more: 1); a step before the outcome: 1/2 whatever its n",
     "question": "How much do small trials overstate effects (small-study effects, trials under 100 or 300 participants)? Is a logarithmic penalty with full weight from about 300 participants supported?"},
    {"id": "F4", "factor": "weight of a null record (a result against the claim)",
     "ours": "its power to detect d = 0.4 at two-sided 5% (n unknown taken as 40): n 40: 0.24; 100: 0.52; 200: 0.81; 400: 0.98",
     "question": "Is weighting a null result by its power (rather than its sample size or not at all) supported? Is d = 0.4 a defensible smallest effect of interest for ageing interventions?"},
    {"id": "F5", "factor": "effect size stated",
     "ours": "a record for the claim with a stated effect of at least medium size (d 0.5) weighs 1, otherwise (small, none or not stated) 1/2",
     "question": "Does a large effect warrant more confidence (GRADE rating up) and a small or unstated one less? Are effects in early or small trials inflated (winner's curse), so that a large effect should rather weigh less?"},
    {"id": "F6", "factor": "comparison",
     "ours": "between groups 1; within one group (before and after) or none 1/2",
     "question": "How much do before-after (uncontrolled) designs overstate effects compared with controlled comparisons (regression to the mean, natural course, placebo response)?"},
    {"id": "F7", "factor": "context (directness)",
     "ours": "adjacent (another population, age, sex, species, dose or schedule than the claim fixes) 1/2; exact and the same class of intervention 1",
     "question": "What do GRADE and empirical studies say about indirectness: how much weaker is evidence from another population, or from another intervention of the same class? Is counting the same class at full weight defensible?"},
    {"id": "F8", "factor": "independence: several records of one trial",
     "ours": "the strongest record of one trial or cohort counts fully, each further one 1/4",
     "question": "How should several publications or outcomes of one trial be counted (duplicate publication, outcome multiplicity)?"},
    {"id": "F9", "factor": "from records to the strength of a link",
     "ours": "S = 1 / (1 + exp(-2.68 (F - A))), F and A the summed weights for and against; F - A = 0.6 alone gives S = 5/6",
     "question": "Are there published schemes that turn a weighted count of studies for and against into a probability or a level of confidence (vote counting with weights, evidence maps, Bayesian evidence synthesis)? What do they say about combining many weak studies against one strong one?"},
]

INSTRUCTIONS = """You are an expert in evidence-based medicine and research methodology. A method for scoring hypotheses about ageing
interventions weighs each published finding (a "record") by factors shaped after GRADE. GRADE gives levels, not numbers, so the
numbers below are the method's own. For each factor, find the PUBLISHED GROUNDS for its value:
- methodological standards and handbooks (GRADE, Cochrane Handbook, CONSORT and similar) - what they say and where;
- empirical, meta-epidemiological studies that MEASURE the size of the effect of the factor (for example a ratio of odds ratios
  between non-randomised studies and RCTs, how much small trials overstate effects, how often animal findings translate).

For each factor answer:
- sources: up to 5, the most informative first; each a real PubMed paper with its PMID, exact title, first author and year,
  what it shows IN NUMBERS where it has them, and one verbatim quote from its abstract that carries the number or the claim;
  a handbook chapter without a PMID may be named with its title, edition and section instead;
- verdict on our value: supported | too_high | too_low | no_evidence, and a one-sentence reason;
- suggested_value: the value the sources support (a number or a rule), or "keep".

Rules: only real papers - a PMID you are not sure of is left out; a quote is copied verbatim from the abstract (one passage);
prefer meta-epidemiological studies and systematic methodological reviews to opinion; say plainly when no evidence exists.

Answer with one JSON object, nothing else:
{"task": "pack_24", "factors": [{"id": "F1", "sources": [{"pmid": "", "title": "", "first_author": "", "year": 0,
  "shows": "", "quote": "", "kind": "standard | meta_epidemiological | empirical | review | other"}],
  "handbook_sections": [{"title": "", "section": ""}], "verdict": "supported | too_high | too_low | no_evidence",
  "reason": "", "suggested_value": ""}], "general_notes": ""}"""


def build() -> dict:
    DIR.mkdir(parents=True, exist_ok=True)
    task = {"task": "pack_24", "instructions": INSTRUCTIONS, "factors": FACTORS}
    f = DIR / "pack_24_task.json"
    f.write_text(json.dumps(task, indent=1, ensure_ascii=False) + "\n")
    return {"factors": len(FACTORS), "kb": round(f.stat().st_size / 1024, 1)}


def check() -> dict:
    from hyparena.tools import pubmed
    from scripts.argon.generation_tasks import quote_found, title_matches
    from scripts.search.bench_search import summaries
    ans = json.loads((DIR / "pack_24_answer.json").read_text())
    srcs = [(f["id"], s) for f in ans.get("factors") or [] for s in f.get("sources") or [] if str(s.get("pmid", "")).strip().isdigit()]
    cache: dict = {}
    summaries(sorted({str(s["pmid"]).strip() for _, s in srcs}), cache)
    abstracts = pubmed.fetch([p for p, v in cache.items() if v.get("exists")])
    rows = []
    for fid, s in srcs:
        p = str(s["pmid"]).strip()
        meta, a = cache.get(p, {}), abstracts.get(p) or {}
        rows.append({"factor": fid, "pmid": p, "exists": meta.get("exists", False),
                     "title_matches": title_matches(s.get("title", ""), meta.get("title", "")) if meta.get("exists") else None,
                     "quote": quote_found(s.get("quote", ""), a.get("title", ""), a.get("abstract", "")) if a else "paper not found"})
    out = {"sources": len(rows), "exist": sum(r["exists"] for r in rows), "title_matches": sum(bool(r["title_matches"]) for r in rows),
           "quotes_verbatim": sum(r["quote"] == "whole" for r in rows), "rows": rows}
    (DIR / "pack_24_check.json").write_text(json.dumps(out, indent=1) + "\n")
    return {k: v for k, v in out.items() if k != "rows"}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("cmd", choices=["build", "check"])
    print(json.dumps(build() if ap.parse_args().cmd == "build" else check(), indent=1))


if __name__ == "__main__":
    main()

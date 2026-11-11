# hyp-arena

A research prototype for ranking hypotheses about ageing and healthy lifespan. The current method (**v3.8**) reads a
hypothesis as a **mechanism chain** from the intervention to the outcome. Each link is checked against PubMed papers
published before the date of scoring; every finding is a record with a verbatim quote and a weight built on the GRADE
domains (design, precision, effect, comparison, context). From the records the code computes the **evidence balance** of the
chain (−1 … +1, over the links that have data), **novelty** N, **informativeness** I (which supported competing
explanations the stated experiment rules out), **scope** W and **feasibility**, and ranks the hypotheses with **ASPID**
(SMAA) under three preference profiles (evidence, funding, frontier): each hypothesis gets an expected score and a
probability of being in the top, and a list of what would raise it. How it works and how to read a report:
[`docs/method-v3-manual.md`](docs/method-v3-manual.md).

Status (2026-11-11): work in progress.

- **What is checked, and how.** Every check is a file in [`specs/`](specs/) with its definitions written before the
  computation and the result appended; the summary table is in the manual, section 12. Reading fields (design, n, blinding)
  agree with an outside reader at 92-96%; the record weight orders later trials of the same link (AUC 0.70); against trial
  outcomes the evidence balance is weak (AUC about 0.59, in-sample), and two LLMs asked directly do better on the same trials
  (0.76; leakage not excluded). The clean test is prospective: 60 ongoing trials that report between November 2026 and
  December 2028 were scored on 2026-11-06 and the scores frozen with a hash
  ([`specs/prospective-2026-11-06.yaml`](specs/prospective-2026-11-06.yaml)).
- **The bottleneck is reading papers**, not finding them: each paper is now parsed once into a fixed skeleton (the core of
  the knowledge graph, [`specs/paper-skeleton-2026-11-09.yaml`](specs/paper-skeleton-2026-11-09.yaml)); stage 0 reached
  recall 0.52 at precision 0.85 against an outside reader.
- Deferred work: [`docs/backlog.md`](docs/backlog.md); the latest hand-off between sessions: the newest
  `docs/handoff-*.md`.

The rankings are research output, not medical advice. The site <https://danrd.github.io/hyp-arena/site/> still shows the
method v2 example run (being rewritten).

Data sources: PubMed and PMC (NCBI E-utilities), DrugAge (HAGR, CC BY 3.0; de Magalhães et al. 2024), ChEMBL, ChEBI (OLS4),
ClinicalTrials.gov and the other trial registries named in the benchmark. Code under the MIT licence ([`LICENSE`](LICENSE)).

## Documentation

- **Method manual** (the current rules, why each one, how to read a report, validation status): [`docs/method-v3-manual.md`](docs/method-v3-manual.md)
- **How the system works, step by step, why, and how each step is checked** (in Russian, for colleagues): [`docs/system/steps.md`](docs/system/steps.md), diagram [`docs/system/scheme.drawio`](docs/system/scheme.drawio)
- Checks and decisions, one file each: [`specs/`](specs/); plans of checks in progress: [`docs/plans/`](docs/plans/)
- Benchmark of registry hypotheses: [`docs/benchmark.md`](docs/benchmark.md); Bio Arena: [`docs/bioarena.md`](docs/bioarena.md)
- Card format and relation vocabulary (shared with the knowledge graph): [`docs/spec/hypothesis-card-spec.md`](docs/spec/hypothesis-card-spec.md); ASPID implementation: [`docs/spec/aggregation-spec.md`](docs/spec/aggregation-spec.md); data sources: [`docs/spec/data-sources.md`](docs/spec/data-sources.md)
- Commands (tests, runs, reports, tools): [`docs/commands.md`](docs/commands.md)
- How Co-Scientist works (reference): [`docs/co-scientist-reference.md`](docs/co-scientist-reference.md)
- Validation criteria of the v2-era tests (generated): [`docs/validation-criteria.md`](docs/validation-criteria.md)
- Archive (method v2, earlier v3 rules, old hand-offs and drafts): [`docs/archive/`](docs/archive/README.md)

Quick start: `pip install -e . pytest && python -m pytest tests/`.

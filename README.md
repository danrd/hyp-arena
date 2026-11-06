# hyp-arena

A research prototype for ranking hypotheses about ageing and healthy lifespan. The current method (v3.2) reads a hypothesis
as a **mechanism chain** from the intervention to the outcome; each link is checked against PubMed abstracts (date-cut,
verbatim quotes, every record weighed by design, sample size, effect, comparison and context); the code computes
**plausibility** P (with an interval), **informativeness** I (which supported alternatives the stated experiment rules out),
**scope** and further indicators, and ranks the hypotheses with **ASPID** (SMAA) under explicit preference profiles, which
gives each one an expected value and a probability of being in the top rather than a single score. How it works and how to
read a report: [`docs/method-v3-manual.md`](docs/method-v3-manual.md).

Status (2026-11-06): work in progress. Extraction of design, comparison and sample size passes on hand-labelled sets. P
against trial outcomes: tied AUC 0.65 on 30 calibration trials and 0.61-0.64 on a fresh sample of 40 (small samples, wide
intervals; earlier methods showed no signal). The clean test is prospective: 60 ongoing trials that report between November
2026 and December 2028 were scored on 2026-11-06 and the scores frozen with a hash before any outcome
([`specs/prospective-2026-11-06.yaml`](specs/prospective-2026-11-06.yaml)). A benchmark of 237 hypotheses written by trial
investigators before the result is frozen ([`docs/benchmark.md`](docs/benchmark.md)). The earlier method v2 (rule-based
indicators over a verified card) and a Co-Scientist-style tournament (Elo) are kept as baselines. The rankings are research
output, not medical advice.

The site <https://danrd.github.io/hyp-arena/site/> shows an example run (the Elo tournament next to the ranking under
preference profiles, the verified card of each hypothesis), lets you download the results, and explains how to rank your
own hypotheses with your own API key.

Data sources: PubMed (NCBI E-utilities), DrugAge (HAGR, CC BY 3.0; de Magalhães et al. 2024), ChEMBL, ChEBI (OLS4),
ClinicalTrials.gov and the other trial registries named in the benchmark. Code under the MIT licence ([`LICENSE`](LICENSE)).

## Documentation

- Approach and lines of work: [`docs/approach.md`](docs/approach.md)
- **Method v3.2 manual** (how a hypothesis is scored, the indicators and profiles, how to read a report, validation status): [`docs/method-v3-manual.md`](docs/method-v3-manual.md); specification with history and decisions (in Russian): [`docs/spec/method-v3.md`](docs/spec/method-v3.md); every test with its criterion written before the run: [`specs/`](specs/)
- Method v2 (verified card → rule-based indicators → aggregation; now a baseline): [`docs/rules-method.md`](docs/rules-method.md); specifications in [`docs/spec/`](docs/spec/)
- Validation criteria and their status: [`docs/validation-criteria.md`](docs/validation-criteria.md)
- Method v3 manual (how a hypothesis is scored, how to read its analysis report; can be attached to a hypothesis as context): [`docs/method-v3-manual.md`](docs/method-v3-manual.md); reports by code: `python -m hyparena.analyze RUN.json`
- Benchmark of registry hypotheses: [`docs/benchmark.md`](docs/benchmark.md)
- Comparison with Co-Scientist-style baselines: [`docs/comparison.md`](docs/comparison.md); how Co-Scientist works: [`docs/co-scientist-reference.md`](docs/co-scientist-reference.md)
- Architecture: [`docs/architecture.md`](docs/architecture.md)
- Commands (tests, backtests, the benchmark, tools): [`docs/commands.md`](docs/commands.md)

Quick start: `pip install -e . pytest && python -m pytest tests/`.

# hyp-arena

A research prototype that evaluates and ranks hypotheses about ageing and healthy lifespan, and suggests how to make them
stronger.

**What it does.** A hypothesis (a registered trial, a written idea or a generated one) is turned into a structured card:
the population, the intervention, the outcome it promises and the steps of the mechanism in between. For each part the
system searches the scientific literature published before the date of scoring, reads the papers it finds and records
every finding with a verbatim quote and a weight (study design, size, effect, how close the study is to the claim). From
these records it estimates how well supported the hypothesis is, how new it is, how informative its proposed experiment
is (which competing explanations the experiment would rule out) and how feasible it is. The hypotheses are then ranked
under several preference profiles (evidence, funding, frontier research) with a method for aggregating indicators when
their weights are only partly known: ASPID (Hovanov's analysis and synthesis of indicators under information deficiency),
equivalent here to SMAA (Stochastic Multicriteria Acceptability Analysis). Each hypothesis gets an expected score, the
probability of being among the top ones, and a list of what would raise it.

**Direction of the work.** Every stage of the system (card, search, reading, evidence summary, novelty, competing
explanations, ranking, improvement of hypotheses) gets its own benchmark: a fixed set of inputs, a gold standard from an
outside reader, a measure and a threshold written before the run, and a comparison with a plain LLM asked directly. Stages
are improved one at a time against their benchmarks, starting from the ones every later stage depends on. The final test
is prospective: scores of ongoing trials are frozen before their results are known.

The rankings are research output, not medical advice.

Data sources: PubMed and PMC (NCBI E-utilities), DrugAge (HAGR, CC BY 3.0; de Magalhães et al. 2024), ChEMBL, ChEBI (OLS4),
ClinicalTrials.gov and other trial registries. Code under the MIT licence ([`LICENSE`](LICENSE)).

## Documentation

- **Method manual** (the current rules, why each one, how to read a report, validation status): [`docs/method-v3-manual.md`](docs/method-v3-manual.md)
- **How the system works, step by step, and how each step is checked** (in Russian): [`docs/system/steps.md`](docs/system/steps.md), diagram [`docs/system/scheme.drawio`](docs/system/scheme.drawio); stage manuals: the card — [`docs/system/card.md`](docs/system/card.md)
- **Benchmarks by stage**: [`docs/benchmarks/README.md`](docs/benchmarks/README.md); checks and decisions, one file each: [`specs/`](specs/); plans of work in progress: [`docs/plans/`](docs/plans/)
- Benchmark of registry hypotheses: [`docs/benchmark.md`](docs/benchmark.md)
- Card format and relation vocabulary (shared with the knowledge graph): [`docs/spec/hypothesis-card-spec.md`](docs/spec/hypothesis-card-spec.md); the ranking method (ASPID / SMAA): [`docs/spec/aggregation-spec.md`](docs/spec/aggregation-spec.md); data sources: [`docs/spec/data-sources.md`](docs/spec/data-sources.md)
- Commands (tests, runs, reports, tools): [`docs/commands.md`](docs/commands.md)
- Deferred work: [`docs/backlog.md`](docs/backlog.md); changes by stage: [`docs/system/changelog.md`](docs/system/changelog.md)
- Archive (method v2, earlier v3 rules, old hand-offs and drafts): [`docs/archive/`](docs/archive/README.md)

Quick start: `pip install -e . pytest && python -m pytest tests/`.

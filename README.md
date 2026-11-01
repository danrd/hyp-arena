# hyp-arena

A research prototype for ranking hypotheses about ageing and healthy lifespan. Each hypothesis is turned into a
structured card of claims; the claims are checked against PubMed abstracts and DrugAge with verbatim quotes; rules
compute indicators from the checked evidence (effect level, robustness, path to humans, novelty and others); the
hypotheses are then ranked under explicit preference profiles with SMAA, which gives each one an interval and a
probability of being in the top k rather than a single score. A Co-Scientist-style tournament (Elo) is included as
a baseline.

Status: work in progress. So far the method has been evaluated on worked examples, a negative-sampling test and
historical backtests against the Interventions Testing Program; the samples are small and the results are reported with
their intervals in [`docs/rules-method.md`](docs/rules-method.md) and [`docs/validation-criteria.md`](docs/validation-criteria.md).
The main test now being prepared is a benchmark of 237 hypotheses written by trial investigators before the result
(ClinicalTrials.gov, ISRCTN and the German, Dutch and Australian–New Zealand registries), each evaluated as of its registration date:
[`docs/benchmark.md`](docs/benchmark.md). The rankings are research output, not medical advice.

The site <https://danrd.github.io/hyp-arena/site/> shows an example run (the Elo tournament next to the ranking under
preference profiles, the verified card of each hypothesis), lets you download the results, and explains how to rank your
own hypotheses with your own API key.

Data sources: PubMed (NCBI E-utilities), DrugAge (HAGR, CC BY 3.0; de Magalhães et al. 2024), ChEMBL, ChEBI (OLS4),
ClinicalTrials.gov and the other trial registries named in the benchmark. Code under the MIT licence ([`LICENSE`](LICENSE)).

## Documentation

- Approach and lines of work: [`docs/approach.md`](docs/approach.md)
- The method (verified card → rule-based indicators → aggregation under preference profiles): [`docs/rules-method.md`](docs/rules-method.md); specifications in [`docs/spec/`](docs/spec/)
- Validation criteria and their status: [`docs/validation-criteria.md`](docs/validation-criteria.md)
- Benchmark of registry hypotheses: [`docs/benchmark.md`](docs/benchmark.md)
- Comparison with Co-Scientist-style baselines: [`docs/comparison.md`](docs/comparison.md); how Co-Scientist works: [`docs/co-scientist-reference.md`](docs/co-scientist-reference.md)
- Architecture: [`docs/architecture.md`](docs/architecture.md)
- Commands (tests, backtests, the benchmark, tools): [`docs/commands.md`](docs/commands.md)

Quick start: `pip install -e . pytest && python -m pytest tests/`.

# Task for Codex: network proximity of an intervention's targets to the ageing modules

Written 2026-11-06 (user decision: a separate task, not done in the Claude session). Context: the Eternal Search
presentation «Спектр борьбы со смертью» (Open Longevity) and SHARP — Gross, Ehlert, Gladyshev, Loscalzo, Barabási,
"Network-driven discovery of repurposable drugs targeting hallmarks of aging", *Nature Aging* 2026 (open version on PMC).
Method: Guney, Menche, Vidal, Barabási, "Network-based in silico drug efficacy screening", *Nat Commun* 2016.

## Why

In method v3 a mechanism link without any literature record is "unverified" (S = 0.5 in v3.2): the method cannot tell an
unverified link that biology makes likely from one it does not. The proximity of the intervention's targets to an ageing
module on the human interactome is a code-computed prior for such links and a candidate ASPID indicator (evidence and
evolution profiles). It is admitted only through the four conditions of `docs/spec/method-v3.md` section 13 (reliability,
separation, non-redundancy, own question), checked by the Claude session afterwards — this task builds and validates the
computation, it does not change the scoring.

## Inputs (all public, free)

- **Interactome**: the one SHARP uses if it is downloadable (state which); otherwise STRING v12 human, physical links,
  combined score ≥ 700, or HuRI + literature-curated binary links. Record the source, version, date and SHA-256.
- **Ageing genes and modules**: OpenGenes (`https://open-genes.com/api/gene/search?pageSize=3000`; the snapshot of
  2026-11-06 is in `data/cache/opengenes.json`, gitignored: refetch and record the date). Module of a hallmark = OpenGenes
  genes mapped to that hallmark (`agingMechanisms` → the 11–12 hallmarks of López-Otín 2023; write the mapping table
  into the repo) restricted to the largest connected component on the interactome. Also one module of all OpenGenes genes
  with confidence "moderate" or higher.
- **Targets**: ChEMBL mechanism targets of a compound (`hyparena/tools/compounds.py`: `lookup(name).targets`, gene symbols
  from `target_names`, official symbols only).

## Computation (Guney et al. 2016)

- d_c(T, M): mean over targets t of the shortest-path distance from t to the nearest gene of module M.
- z = (d_c − μ) / σ against 1000 random target sets of the same size, sampled with degree-preserving binning (bins of at
  least 100 nodes), fixed seed. Report d_c, z and the empirical p for each module; the indicator candidate is the minimum
  z over the hallmark modules and the hallmark that gives it.
- A function `proximity(compound_name, as_of=None) -> dict | None` (None: no target gene on the interactome) in
  `hyparena/card/network_proximity.py`, with the graph and the random references cached under `data/cache/network/`
  (gitignored).

## Validation (before anything else uses it)

1. **Reproduce SHARP's check**: the ITP compounds (`longevity-kg/hypothesis_sources/itp_experiments.yaml`, 63 agents, outcomes
   by sex): does min z separate lifespan-extending from no-effect agents? Tied AUC with a bootstrap CI; compare with the
   paper's claim ("8 of 8 ITP lifespan-extending agents predicted"). Write the criterion (what AUC counts as reproduced)
   into `specs/network-proximity-<date>.yaml` **before** computing it.
2. **Robustness**: z with a second interactome or with the score threshold 400; Spearman of the two rankings.
3. **Coverage**: share of compounds with at least one target on the interactome — on ITP, DrugAge compounds
   (`data/drugage_compounds.json`) and the calibration and prospective units (`longevity-kg/hypothesis_sources/calibration/`,
   `.../prospective/`); expect low coverage on registry trials (mostly programmes).
4. **Leakage note**: OpenGenes and the interactome are current snapshots; for retrospective units they contain later
   findings. State it; do not try to rebuild past versions.

## Rules (as for every task in this project)

- No paid model calls. Unit tests for the distance and the z-score on a toy graph (`tests/test_network_proximity.py`); the
  whole suite must pass (`python -m pytest -q -k "not evolve and not v3_pipeline_runs_with_the_fake_llm"`).
- **Logs, intermediate tables and reports go to `longevity-kg/hypothesis_sources/network/`** (private), not to
  `hyp-arena/reports/` and not to a branch of the public `hyp-arena`. Into `hyp-arena` go only code, tests, the hallmark
  mapping table and the spec with its result. No copies of `longevity-kg` files and no publisher texts in `hyp-arena`.
- Large downloads stay in `data/cache/` (gitignored); record URL, version and SHA-256 in the spec instead.
- Commit to `main` directly with clear messages; no model identifiers in commits.
- End with a short report (Russian) in `longevity-kg/hypothesis_sources/network/README.md`: what was built, the three
  validation results, open questions.

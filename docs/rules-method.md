# Our method, version 2: verified card → rule-based indicators → aggregation

Design decided in the working notes on 2026-10-19 (sections 2.1–2.4); specifications in `docs/spec/`
into `docs/spec/` (card format, worked examples, aggregation). The LLM tournament over the whole pool (ladder
step L4) is kept as an intermediate step for comparison; the two Co-Scientist baselines (L0, L0ts) keep their
tournaments. The 2026 baseline's plagiarism penalty and claim-versus-log checks are not reproduced: both act on
generated ideas and manuscripts, and external hypotheses have no experiment logs (decision 2026-10-19).

| Step | Who | Status |
|---|---|---|
| Normalizer: text → declared card (claims in a closed vocabulary, each with a verbatim `source_span`) | LLM (`normalize_card/v2`, gemini-3.5-flash), code validates and asks again: `hyparena/card/normalizer.py` | done |
| Validation and admission (accepted / needs refinement / not a hypothesis) | code: `hyparena/card/rules.py` | done |
| Verifier: evidence records with verbatim quotes, quote role, context match, endpoint; analog probes in mice for human outcomes | DrugAge (curated, deterministic) + PubMed abstracts (LLM extracts with `verify_claim/v2`; code drops quotes that are not verbatim): `hyparena/card/verifier.py` | done |
| Claim statuses, gate, evidence profile, next step, known result | code: `hyparena/card/rules.py` | done |
| Indicators (spec 8a) | code: `hyparena/card/indicators.py` | done for evidence-based ones; cost, time, late start and informativeness stay unknown until their inputs exist |
| Aggregation under preference profiles (МРСП / SMAA-2) | code: `hyparena/aspid.py`, profiles in `configs/profiles.yaml` | done |
| Ranking across profiles, robust candidates | code: `hyparena/card/rank.py` | done |
| End to end | `python -m hyparena.card.pipeline --paste file.txt --out result.json` (`configs/v2.yaml`, `--fake` for no model calls) | done |
| Debates on the top (prosecution vs defence; competitor pairs) | LLM | later |
| Card-based proximity, alternatives and prediction table, evolution loop | code + LLM | later |

**Aggregation as implemented** (Aggregation_Spec):
- additive value over indicators in [0, 1];
- cardinal indicators on fixed reference scales (no min–max over the pool);
- ordinal indicators with the SMAA-O random monotone mapping;
- unknown values drawn uniformly in every iteration;
- weights uniform over the profile's admissible set: exact for no constraints and for complete tiers, hit-and-run (parallel chains) for partial orders and equal groups;
- outputs from one pass with common random numbers: expected value, spread, quantiles, pairwise winning indices (ties count half), rank acceptabilities, P(top-k), P(best), central weights, confidence factors (central weights fixed, data varied), Monte Carlo half-width. Exact ties in a draw share places at random.

**Tests** (`python -m pytest tests/`):
- the worked examples as fixtures (`tests/fixtures/cards`): statuses, gate, profile, next step, admission, known result, the endpoint trap;
- the checks of Aggregation_Spec section 7: uniform simplex, centroid weights by both samplers, dominance, symmetry, unknowns widen the spread, Monte Carlo error, independence from the pool;
- an end-to-end ranking of the examples.

**Profiles** (`configs/profiles.yaml`, all drafts until set with experts): `evidence_first` (verified evidence first), `cheap_feasible` and `fundamental` (the examples in the notes).

## Check against the worked examples (2026-10-19)

The raw texts of the card-spec examples run through the whole pipeline (normalizer and verifier on cheap models; the examples' expected cards and verified layers are in `tests/fixtures/cards`). About 40 model calls in total over the attempts below.

| Example | Expected (spec) | Pipeline |
|---|---|---|
| 1. Low-dose rapamycin, human healthspan | mammals · replicated · ITP positive · mechanism partial · human_markers contested · next: trial with pre-registered primary outcome | the same. PEARL (PMID 40188830) is found and split into a supporting subgroup record and a refuting null primary outcome |
| 2. D+Q, physical function | mammals (analog in aged mice) · single · partial | mammals · **replicated** (the verifier found a second independent mouse study, PMID 25754370) · partial |
| 3. Rapamycin mainly via cancer, not aging | filtered: "not by slowing aging" refuted by PMID 22587563 | **known result**: the normalizer makes "rapamycin suppresses death from cancer" the outcome (supported, PMID 22107964), and retrieval does not find PMID 22587563 for the "not by slowing aging" claim |
| 4. "Senolytics slow aging" | needs refinement (population, endpoint) | the same |
| 5. "Senescent cells are bad for health" | not a hypothesis | the same |
| 6. Resveratrol from middle age, mouse lifespan | filtered (refuted) | the same: DrugAge records of the two ITP papers (PMID 20974732, 22451473) refute it |

**What it took:**
- **Normalizer.** A worked example in the prompt (on metformin, deliberately not one of the fixtures), rules for mechanistic hypotheses, and "aging" and "health" as non-measurable endpoints. Also a stronger model: gemini-3.5-flash split example 3 correctly, while gpt-5-nano, gemini-3.1-flash-lite and gpt-5-mini kept the premise as the outcome.
- **Verifier.** Rules for negative claims and for primary versus secondary or subgroup outcomes (`verify_claim/v2`); the analog probes in mice; a third search query.
- **DrugAge.** A paper counts against a lifespan claim only if neither average nor maximum lifespan rose significantly. PMID 22107964 is listed with a non-significant mean, but the paper reports longer survival of the last survivors.

**Departures from the specification found on the way (to decide):**
1. Example 6's expected card has comparator "standard diet", which the raw text does not state. With the text as written, a high-calorie-diet study (PMID 17086191) also matches, and the rules give "contested" unless DrugAge's ITP records settle it. The ITP records did settle it here, and the hypothesis is filtered as expected.
2. Example 2's expected c1 has species "human"; the text does not say so. With species unknown, mouse evidence matches, and the claim becomes supported.
3. Hypotheses of the form "mainly X, not Y" (example 3) carry their point in the contrast. The outcome claim should be the contrast. This is a normalizer rule to add, and a known weak spot until then.
4. Claims with relation `other` get the status `unresolved` (spec 5: ignored by symbolic checks).

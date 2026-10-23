# Our method, version 2: verified card → rule-based indicators → aggregation

Design decided in the working notes on 2026-10-19 (sections 2.1–2.4); specifications in `docs/spec/`
into `docs/spec/` (card format, worked examples, aggregation). The LLM tournament over the whole pool (ladder
step L4) is kept as an intermediate step for comparison; the two Co-Scientist baselines (L0, L0ts) keep their
tournaments. The 2026 baseline's plagiarism penalty and claim-versus-log checks are not reproduced: both act on
generated ideas and manuscripts, and external hypotheses have no experiment logs (decision 2026-10-19).

| Step | Who | Status |
|---|---|---|
| Normalizer: text → declared card (claims in a closed vocabulary, each with a verbatim `source_span`; qualifiers inherited from PICO marked; contrast "mainly X, not Y" as outcome X plus a rejected alternative Y) | LLM (`normalize_card/v4`, gemini-3.5-flash), code sets inheritance of species and strain (deterministic), validates and asks again: `hyparena/card/normalizer.py` | done |
| Compound identifiers: interventions typed as compounds → PubChem parent compound, ChEBI, ChEMBL, max clinical phase, first approval year, synonyms | code: `hyparena/tools/compounds.py`, `hyparena/card/entities.py`; DrugAge names mapped once in `data/drugage_compounds.json` | done (compounds only) |
| Validation and admission (accepted / needs refinement / not a hypothesis) | code: `hyparena/card/rules.py` | done |
| Verifier: evidence records with verbatim quotes, quote role, context match, endpoint; rejected alternatives checked like claims; analog probes in mice for human outcomes | DrugAge (curated, deterministic) + PubMed abstracts (LLM extracts with `verify_claim/v5`; code drops quotes that are not verbatim, checks the context and the strain, see below): `hyparena/card/verifier.py` | done |
| Claim statuses (with the contrast rule), gate, evidence profile, next step, known result | code: `hyparena/card/rules.py` | done |
| Indicators (spec 8a) | code: `hyparena/card/indicators.py` | done for evidence-based ones and `path_to_human`; late start and informativeness stay unknown until their inputs exist |
| Aggregation under preference profiles (МРСП / SMAA-2) | code: `hyparena/aspid.py`, profiles in `configs/profiles.yaml` | done |
| Ranking across profiles, robust candidates | code: `hyparena/card/rank.py` | done |
| End to end | `python -m hyparena.card.pipeline --paste file.txt --out result.json` (`configs/v2.yaml`, `--fake` for no model calls) | done |
| Expert layer (card spec 7a; Aggregation_Spec 6a): sources sent through the verifier, opinions kept apart, pairwise choices as weight constraints, the expert's own hypotheses | `hyparena/card/expert.py`, `Prefer` / `check_feasible` / `next_pair` in `hyparena/aspid.py`; `--expert expert.yaml` | done (file input; no interface yet) |
| Alternatives row (spec 8c): declared rejected alternatives with their status, 14 checklist rows by rules, one check call per hypothesis, a dedicated search for P(top-k) ≥ 0.5 | code + LLM (`check_alternatives/v1`): `hyparena/card/alternatives.py` | done |
| Backtest pools and metrics (Working_Notes A2) | code: `hyparena/outcomes.py`, `hyparena/backtest.py` | done (no run yet) |
| Debates on the top (prosecution vs defence; competitor pairs), prediction table, informativeness | LLM | stage C |
| Card-based proximity (spec 8b): duplicate, variant, competitor, contradiction, analog (shared ChEMBL mechanism target or narrow ChEBI class), mechanism neighbour (shared hallmark or molecular node); embedding fallback for unresolved names (SapBERT, approximate); duplicates are not verified twice, competitors become alternatives | code: `hyparena/card/proximity.py`, `hyparena/tools/chebi.py`, `hyparena/tools/embed.py` | done (refinement siblings not linked) |
| Evolution loop | code + LLM | later |

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

**Profiles** (`configs/profiles.yaml`, all drafts until set with experts): `evidence_first` (verified evidence first), `cheap_feasible` (path_to_human ≥ novelty ≥ effect_level) and `fundamental` (mechanism, informativeness, novelty ≥ path_to_human; path_to_human took the place of cost).

## Spec decisions of 2026-10-20 in the code

- **Schema.** PICO `age` → `age_at_start` (old cards are read); `intervention.route` (diet, water, oral, injection, topical, other, unknown); qualifiers `measure` and `contrast`; `Admission.known_result`; refusal types a closed list (type, direction, species, endpoint, inherited mismatch); `origin: expert`; the short verified-layer form `claim: {subject, relation, object}` for analogs; `comparator: unknown`.
- **Inheritance (spec 9), code-enforced.** Only species and strain; only into claims and rejected alternatives about the intervention; only when the span does not name the key (an organism in the span counts); never into molecular relations; mandatory when the conditions hold, so `mark_inherited` makes the result deterministic and `validate_card` reports a missing one; for organism relations the inherited species also fills the object (the old object label moves to `measure`).
- **Human rungs.** Evidence records carry `human_rungs` (markers: laboratory and instrumental measures; clinical: function, frailty, pain, disease, mortality); a human claim has a status per rung (`rung_status`). Subgroup rule (spec 7, "Subgroup-only support", 2026-10-21): support flagged `subgroup_only` (or `secondary_outcome`) never gives `supported` on its own. With admissible counterevidence for the claim (at any rung) the rung is contested and the conflict lists that counterevidence; without it the rung is `unverified` and the claim carries the flag `subgroup_unchecked`, the same answer as `contrast_unchecked` (an unfound null is not a finding). Before that, the verifier makes one targeted query (`check_subgroup/v1`): the same papers' abstracts plus the ClinicalTrials.gov record of each NCT id the abstract names (registered primary outcomes, and posted primary results when the trial has them), asking for the whole-sample result on the primary outcome. A verbatim null or negative result goes to counterevidence (contested), a positive one to evidence (supported); a registry quote is a record `ClinicalTrials.gov` with the NCT id and `linked_pmid`. The subgroup record stays in evidence, visible to judges and the expert.
- **Strain rule.** The card's strain unspecified → `n/a`. Specified and different → the record moves to an analog `an<N>` (same intervention and species, other strain): it counts for the effect level, not for the known result, and novelty becomes `new_context`. An inherited strain that differs also leaves an `inherited_mismatch` refusal. Code sets `qualifiers_match.strain` (left out when the record reports no strain); "genetically heterogeneous" matches UM-HET3 and outbred stocks.
- **Evidence records.** `sex` (male, female, both, unknown), `strain`, `dose`, `age_at_start` from the verifier (v5: keys the abstract does not report are left out, not guessed) and from DrugAge (one record per paper and strain). Curated `intervention_match` by field rules: the card's route differs from the record's (ppm in food = diet, in drinking water = water) or the card is intermittent and the record continuous → `regimen_differs`; `dose_differs` only from the model.
- **gate_reason.** The refuting record ("PMID:20974732", program records first) or "contrast rule: a1 supported (PMID:22587563)".
- **path_to_human** replaces cost, time and translational distance: preliminary steps before a human trial with marker or function endpoints — a preclinical safety package when there are no human safety data (approved drug, clinical-stage compound or diet count), a mouse study when there is no supported mammalian effect; 0 · 1 · 2, a gene without a drug unknown. As of T: approved if ChEMBL's first approval year ≤ the year of T, clinical stage if ClinicalTrials.gov has a trial with the compound started before T (`hyparena/tools/trials.py`; its intervention search can over-match names). `next_step` stays outside the ranking.
- **Novelty levels** new_context < translation < analog < new_link; `both_sexes` from the records' `sex`; SMAA-O is the default ordinal mapping.
- **Alternatives (spec 8c).** Ids a<N> declared, alt<N> pipeline, an<N> analogs. The checklist rows are included by rules over card and record fields; one call per gate-passing hypothesis over the abstracts the verifier already read: an abstract with the discriminating control and the effect persisting → `excluded_by_evidence` with a verbatim quote; with the effect gone → `supported` (our addition: the spec has only excluded and open); else `open`. A dedicated search per open row only when P(top-k) ≥ 0.5 in some profile. Informativeness stays unknown until stage C.

## Calibration, stages 0-2 (2026-10-21)

Tool: `python -m hyparena.card.check_examples normalize|verify` (worked examples against the reference cards).

**Stage 0** (no models): fake runs on both backtest pools reach the metrics; `backtest audit --v2 run.json` checks
that no record after T reached a run.

**Stage 1, normalizer** (`normalize_card/v4`, 7 texts × 3 repeats per family, 57 calls, no failures):

| | gemini-3.5-flash | deepseek-v4.1-flash (no thinking) |
|---|---|---|
| admission right | 21/21 | 20/21 ("Senescent cells are bad for health" accepted once) |
| type, outcome relation, contrast of Example 3, `measure` | all | all |
| inheritance | 15/15 | 13/15 ("clears senescent cells" parsed as `other`, so no inheritance) |
| spans | complete | once cut ("in mice" lost from Example 1's c4) |
| time | 285 s | 76 s |

Both models vary between `premise` and `mechanism` for the same claim; both roles feed the same axis. The
normalizer stays on Gemini. Code fixes from this stage: the inherited species is written clean ("human", not
"healthy older adults"); a text with nothing measurable is not a hypothesis whatever type it is parsed as.

**Stage 2, verifier** (deepseek-v4.1-flash, reference cards, 3 rounds of 2 repeats, 173 calls). Findings and fixes:
- *Provider content filter.* DeepSeek's endpoint answers some prompts with `finish_reason: content_filter` and no
  text; the trigger in Example 3 is the Wilkinson 2012 abstract (PMID 22587563), the key record. The verifier now
  falls back to another family of the config (Gemini). With 20 abstracts per prompt the filter fires more often:
  in the last round 17 of 42 claims were answered by the fallback.
- *PubMed Best Match is not deterministic.* The same query a second later gives another top 8 (4 of 12 PMIDs
  stable over 6 repeats; Neff 2013 in and out of the top 12). The top 20 is nearly stable (18 of 22), so the
  verifier now reads 20 abstracts per claim.
- *Subgroups.* The extractor did not flag PEARL's "for women using 10 mg" as subgroup-only; code now flags a
  one-sex result when the same paper reports a null result for the claim, and the prompt names subsets.
- *Generic referents.* "intermittent oral administration of senolytics" (Xu et al. 2018) was counted as a related
  compound because the title does not name D+Q; a generic referent in an abstract that names the intervention
  now counts.
- *Human markers.* A marker finding (endpoint biomarker) counts for a human healthspan claim at its markers rung
  (PEARL's null primary outcome was dropped as an endpoint mismatch).
- `gate_reason` of a curated record is its PMID.

Last round against the reference: Example 5 matches in both repeats; Example 3 matches in one repeat (Wilkinson
and Neff found, a1 and c2 contested), in the other X is refuted by "Disease patterns of rapamycin-treated mice did
not differ" (the reading the reference calls "does not support"); Example 2 matches except c3 ("senescent cells
drive physical decline": found in one earlier round, not in this one); Example 1: c1 and c2 now have support from
papers newer than the reference (c2: a 2026 placebo-controlled study in older adults, p21 in immune cells), and in
one repeat the extractor left out PEARL's null primary outcome, so the subgroup result stands alone and c4 is
supported. Fixed by the subgroup rule above: such a c4 is now unverified with `subgroup_unchecked` unless the targeted
query finds the null primary outcome ("Visceral adiposity did not change significantly", in the abstract of
PMID 40188830; the registry record NCT04488601 names visceral fat by DXA as primary and has no posted results).

Fourth round (2026-10-21, after the subgroup rule; 35 calls, no failures; runs/stage2d): Examples 3 and 5 match in
both repeats; Example 2 matches except c3, as before. Example 1, repeat 2: c4 contested as in the reference (the
extractor returned the null primary outcome itself). Repeat 1: c4 unverified, for two reasons outside the new rule:
the extractor marked the dose "no" for PEARL (5–10 mg weekly against "weekly low-dose"), which made the subgroup
record inadmissible, and it gave the null primary outcome stance "neither" with endpoint biomarker, so it became an
`endpoint_mismatch` refusal (the prompt's endpoint instruction predates the rule that human markers count for a
healthspan claim). With the dose set to "yes", the targeted query on that repeat found "Visceral adiposity did not
change significantly" in the abstract (one call), and c4 came out contested at both rungs; the first live call
also showed the model writing source ids in brackets ("[PMID:40188830]"), now read as given. c1 and c2 differ from
the reference as in the previous round (c1: one dose-specific mechanism finding refutes it in repeat 1; many
findings in other contexts make it contested in repeat 2; c2: the 2026 p21 study).

Fixes after the fourth round (agreed 2026-10-21, `verify_claim/v5` amended in place): for a human healthspan claim
the prompt says a human marker finding counts (stance supports or refutes, a null primary outcome refutes); a dose
"no" against a card dose without a number ("weekly, low-dose, intermittent") is n/a (code). Example 1 again, two
repeats (12 calls, runs/stage2e): c4 contested in both, as in the reference; its markers rung also lists the 2026 p21
study as support. c1 is contested and supported against the reference's unverified: the extractor counts
"Rapamycin is widely used as a complete inhibitor of the mTORC1 ..." as a finding, where the reference calls such
sentences background; c2 as before.

**Stage 3, negative-sampling regression (2026-10-21; runs/neg_v2/v2-evidence_first-stage3).** The same six groups
on the cards of 2026-10-20 (`--cards-from runs/neg_v2/v2-evidence_first-flash`), so only the verifier, rules,
proximity and aggregation differ; verifier DeepSeek V4.1 Flash. 169 calls, no failures. Against the refreshed run of
2026-10-20: hit@1 0.50 → 0.50, MRR 0.60 → 0.63, mean rank 3.0 → 2.7, AUC 0.78 [0.59, 0.94] → 0.81 [0.63, 0.96]; the
finding is ranked in every group; nothing collapsed as a duplicate and nothing rejected at admission. Two negatives
changed outcome: Lovaza "via SIRT1" in mice became a known result and oridonin "via mTOR activation" was filtered
(PMID 25075795). No regression; the gain is within the interval. Estimated tokens per group rose from 62k to 415k
(20 abstracts per claim instead of 8).

## Typed proximity (2026-10-21)

`hyparena/card/proximity.py` compares cards by keys, not by text. Keys: the intervention (identifiers of
`pico.intervention`, names when unresolved), the population's species, the explained effect (the outcome claim;
for a mechanistic hypothesis its premise claims) with its direction, the mechanism claims, the context (sex, age at
start, strain, regimen, route, comparator, dose, measure), every claim as a triple (subject, relation family,
object, species) with a direction (extends / shortens / no effect, promotes / suppresses, inhibits / activates,
a negated relation), the ChEMBL mechanism targets of the compounds (`compounds.py` fetches them once) and the
hallmarks and molecular objects of the intervention's own claims.

| type | rule |
|---|---|
| duplicate | same intervention, species, effect and direction, same context, same mechanism claims |
| variant | same core, other context, or a mechanism stated in only one of the two |
| competitor | same core, both state mechanisms, the mechanisms differ (a mechanistic hypothesis: the same premise explained differently) |
| contradiction | a claim triple of one card with the opposite direction in the other |
| analog | other interventions with a shared mechanism target **and** a shared ATC level-4 class (sirolimus, everolimus, temsirolimus: FKBP1A + L04AH / L01EG); `analog_weak` when one of the two has no ATC code (agreed 2026-10-21). Tacrolimus and pimecrolimus bind FKBP1A too but inhibit calcineurin (L04AD, D11AH): not analogs of sirolimus |
| mechanism_neighbour | other interventions acting on the same hallmark or molecular node (both "inhibit mTORC1") |

A pair can carry several types (a competitor in another context is also a variant; opposite mechanism claims
under the same outcome are a contradiction and competitors). Pairs come from buckets (same intervention,
triple, target, node), so a pool of thousands of cards is cheap. In the pipeline: a duplicate of an earlier card
gets the outcome `duplicate` with `duplicate_of`, is not verified and takes the score of the card it duplicates
in the ladder format (`dedup=False` turns this off); competitors are added to each other's alternatives row
(`source: proximity`, `ref`); the result lists all relations (`proximity`) and the groups of variants.
Not done: refinement siblings (`parent_id`), novelty against a knowledge graph.

**Mechanism targets and ATC codes** are read over the parent molecule and all its salt and hydrate forms in
ChEMBL (`compounds.CHEMBL_REV` 2): tacrolimus's ATC codes sit on tacrolimus monohydrate, metformin's mechanisms
on metformin hydrochloride (before this, metformin had no targets). Older cache entries are refetched once.

**Duplicates** (2026-10-21): only the original enters АСПИД, so copies do not take several top-k places; the
original's item carries `repeats` (metadata, not merit); in the ladder format a duplicate gets the original's
score. Approximate duplicates (resting on merged names) are not collapsed: their type is `duplicate_approx`,
visible to the expert and judges, and they are ranked separately (embeddings do not separate opposite claims).

**ChEBI classes** (`hyparena/tools/chebi.py`, OLS4, cached; spec 8b, second round of 2026-10-21): a shared narrow
class gives `analog_weak` only when at least one of the two compounds has no ChEMBL mechanism target (then the
class is the only information); when both have targets, target and ATC decide (sirolimus and tacrolimus share
macrolide lactam and are not analogs). "Narrow" = the most specific common is_a ancestor with at most
`chebi.MAX_DESCENDANTS` descendants (the class size). The cap, 100, is chosen on the backtest pool (2026-10-21):
78 ITP and CITP compounds with a ChEBI id, 2,134 pairs in which at least one compound has no ChEMBL target.
Pairs linked by the most specific common class at each cap:

| cap | pairs | classes (size) |
|---|---|---|
| 25 | 0 | — |
| 50 | 2 | proteinogenic amino acid (38): glycine–leucine |
| 100 | 5 | + oxo dicarboxylic acid (78): alpha-ketoglutarate–oxaloacetate; 11beta-hydroxy steroid (95): aldosterone–dexamethasone |
| 200 | 6 | + 17alpha-hydroxy steroid (114): 17alpha-estradiol–dexamethasone |
| 500 | 16 | + tertiary alpha-hydroxy ketone (230): minocycline–forskolin; guanidines (259): metformin–beta-guanidinopropionic acid; lignan (417); enoate ester (467): dimethyl fumarate–arecoline |

Above about 200 functional-group classes appear (alpha-hydroxy ketone, enoate ester), which say nothing about
mechanism; 100 keeps the pairs that are plausibly related (and 7-hydroxyflavonol, 41, for quercetin–fisetin).
Price of the choice: metformin and beta-guanidinopropionic acid (guanidines, 259) are not linked. Earlier
version, kept for the record: the direct is_a parents with at most 50 descendants. "macrolide lactam" (10) joins rapamycin and everolimus,
"7-hydroxyflavonol" (41) quercetin, fisetin and kaempferol; "ether" (9,036) or "polyphenol" (885) are too broad.
Roles (has_role) are not used: "geroprotector" is a role of rapamycin, quercetin, resveratrol, metformin and
dasatinib alike, so it would make most pairs analogs.

**Embedding fallback for unresolved names** (spec 8b). Entities without identifiers (classes such as
"senolytics", diets, procedures, processes) used to match only by exact name. Now the names are embedded and
near-synonyms merged before the keys are built; a relation resting on a merge carries `approximate` with the
names, and an approximate duplicate is reported but not removed. The model is SapBERT (Liu et al. 2021,
PubMedBERT trained on UMLS synonyms; ONNX int8 export by Xenova, about 110 MB, run locally, `pip install -e
".[embed]"`); without it (or with `HYPARENA_EMBEDDER=none`) there is no fallback. Calibration on 18 synonym and
18 non-synonym pairs of ageing entities (2026-10-21; the set is small, so the threshold is provisional):

| model | synonyms median | non-synonyms median | at the threshold without false merges |
|---|---|---|---|
| bge-small-en-v1.5 | 0.81 | 0.75 | 0.90: 5 of 18 synonyms |
| all-MiniLM-L6-v2 | 0.65 | 0.47 | 0.90: 2 of 18 |
| SapBERT | 0.81 | 0.54 | 0.80 with the number rule: 10 of 18 |

The worst false matches of every model differ in one number (omega-3 / omega-6 0.87, mTORC1 / mTORC2, GLP-1 /
GIP), hence the rule: two names merge only if they contain the same numbers. Missed at 0.80: abbreviations
(SASP), drug classes against their members (SGLT2 inhibitors / gliflozins, statins / HMG-CoA reductase
inhibitors), fish oil / omega-3. On a test pool of 17 unresolved interventions SapBERT merged senolytics =
senolytic drugs, young plasma = plasma from young donors, caloric = calorie = dietary restriction (the last is
broader in the strict sense, hence "approximate"), and kept omega-3 / omega-6, protein restriction and plasma
exchange apart.

## Spec decisions of 2026-10-21 in the code

- **Contrast on a split literature (Example 3).** Neff et al. 2013 (PMID 23863708) is counterevidence to the rejected alternative a1 next to Wilkinson et al. 2012: a1 contested → the outcome contested by the table, `gate: pass`. The row "Y supported → outcome refuted" is a synthetic test (Example 3 without Neff 2013).
- **Searching Y in both directions.** The first query of every claim excludes reviews (`... NOT review[pt]`): reviews only give background, never a status, and push findings out of the first page. PubMed's relevance order drifts: on 2026-10-19 "rapamycin slows aging mice" returned Neff 2013 in the top 8, on 2026-10-21 only in the top 20; without reviews both studies are in the top 8. A rejected alternative is searched with 12 abstracts instead of 8, and the verifier prompt asks for findings on both sides, from every abstract. When the object of a claim is an organism, its `measure` is also a query. `verify_claim/v5` was amended in place (it had not run on a model).
- **`other` on the outcome claim.** The normalizer re-parses once with a hint naming the nearest vocabulary relations (word overlap of the claim's note and span with cue words per relation); still `other` → admission flag `unmapped_relation`, outcome `unparsed`, listed in `unparsed` with the note. `normalize_card/v4` gained the hint block (it had not run on a model either).
- **Nothing disappears silently.** Every input ends with exactly one outcome (ranked, filtered, known_result, needs_refinement, not_a_hypothesis, unparsed, normalization_failed); the result lists `awaiting_refinement` (with `missing_critical`), `unparsed`, `directions`, `normalization_failed`, and reports `outcome_counts` and `outcome_shares`. Refined variants are not generated yet.
- **`late_start`** (`hyparena/card/lifespan.py`, tables in `configs/lifespan_medians.yaml` from Data_Sources 19): control medians for UM-HET3 and C57BL/6J by sex, C. elegans N2 (20 °C, FUdR), Dahomey females (25 °C), humans (WHO life tables, high-income default, world for low- and middle-income settings); verbal ages from the JAX mouse life phases and MeSH age groups. Lookup: species + strain + sex; strain unknown → all strains of the species; sex unknown → the "both" row if there is one (humans), else all sexes; anything not in the table → unknown. With medians [m_lo, m_hi] and ages [a_lo, a_hi] the value is [a_lo / m_hi, min(1, a_hi / m_lo)] (a number for point inputs), e.g. "middle age" in mice 0.34–0.57, "older adults" 0.77–1. The aggregation draws an interval uniformly (`aspid.cardinal_range`); an expert choice takes its midpoint and is marked approximate. Assay conditions (worms 20 °C with FUdR, flies 25 °C): a row applies when the card states none (unstated = n/a, a match); when the card states another temperature or no FUdR anywhere in its text, the value is unknown.

## Lifespan stance by code, context flags (2026-10-20)

Two error types seen in the negative-sampling run (`docs/negative-sampling.md`, section 6):
- **Stance of lifespan findings.** The verifier (`verify_claim/v4`) extracts the direction of a lifespan finding (increase, decrease, no effect); code sets the stance from it, as for DrugAge: a finding supports the claim whose direction it matches (extends ↔ increase, shortens ↔ decrease, no effect or a negated "extends" ↔ no effect) and counts against the others. When the extractor's own stance differs, the record notes it. Before, gpt-5-nano took "Lovaza extends life span" as support for "Lovaza shortens lifespan".
- **Disease models and special conditions** (`configs/disease_models.yaml`, `hyparena/card/contexts.py`): which strain or diet a study used is in the text; what it means is a lookup. A seed table of about 30 models (lupus-prone, cancer-prone, metabolic, neurodegeneration, progeroid and senescence-accelerated strains, short-lived worm mutants, high-calorie diets) is matched against the record's abstract and DrugAge's strain field; a match adds the flag `disease_model`, `short_lived_controls` or `special_diet` with the model's name. Flags alone do not change a status (spec 7); since 2026-10-22 a disease-model label with a disease name and its place changes the context (see below); the profile used to report "mammals (disease models or special conditions only)" when every record at the effect level is flagged. The table is a stand-in until a strain ontology is part of the knowledge graph.

Both reduce errors, they do not remove them: the extractor can still misread the direction, and a model the table does not know, or a strain named only in the full text, goes unflagged.

## Compound identifiers (2026-10-20)

After normalization, every intervention the normalizer typed as a compound is looked up in PubChem by name and mapped to its parent compound, so salts, hydrates and synonyms collapse (sirolimus = rapamycin, quercetin dihydrate = quercetin, 17‐α‐estradiol with any dash). From the parent: the preferred name, InChIKey, the ChEBI id (listed among PubChem's synonyms), the ChEMBL id and maximum clinical phase (ChEMBL, by InChIKey). The card gets `Intervention.id` (ChEBI, else `PubChem:<CID>`); a claim's subject gets an id only when every part of it is one of the card's compounds by name or synonym (a combination: "CHEBI:a+CHEBI:b"). Other subjects are never looked up: "SASP" is also a synonym of sulfasalazine.

Uses:
- "the same intervention" (effect level, novelty, inheritance) compares identifier sets when both sides have them, names otherwise;
- DrugAge rows match the claim's compound by parent CID (all 1,046 DrugAge names mapped once), by name when a name does not map;
- human safety data for `path_to_human` take ChEMBL's max phase and first approval year of the resolved compound (a compound in ChEMBL without a phase counts as preclinical); before, the phase came from a fuzzy name search in Open Targets, which always returns some best match.

PubChem's parent compound drops metal counter-ions, which made zinc, nickel and barium acetate all "acetic acid"; a name whose metal is the active part (lithium, transition and heavy metals, selenium; sodium, potassium, calcium or magnesium with an inorganic anion) keeps its own compound, while drug salts collapse to the drug. Of the 1,046 DrugAge names, 755 map to a compound; 33 compounds carry several DrugAge names (salts and hydrates of a drug, sodium or calcium salts of organic acids; two doubtful merges from PubChem's synonyms: AA26-8 / AA26-9 and Epitalon / Epithalamin).

Classes and mixtures ("senolytics", "omega-3 fatty acids") do not resolve; they are listed in `unresolved_compounds` and keep matching by name. Statuses do not change for an unresolved compound: the text search works with or without an identifier. Genes, proteins, processes and species are not resolved yet. Lookups are cached in `data/cache/compounds.json`; tests use an offline table (`tests/conftest.py`).

## Expert layer (2026-10-20)

An expert file (YAML) next to a run holds decisions and hypotheses written by the expert; it never edits the declared or verified layer (card spec 7a). `hyparena/card/expert.py` documents the format.
- **A decision with a PubMed source** on a claim or a rejected alternative: the PMID is fetched together with the search results for that claim and goes through the verifier like any abstract; the record notes which decision gave it. The status changes only through the usual rules.
- **A decision without a source** stays in the layer and appears in the output as "expert opinion".
- **Pairwise** ("prefer H-A" on [H-A, H-B], optionally for one profile): the constraint sum_j w_j (q_Aj − q_Bj) ≥ 0 in that profile, whose version gets "+expert-N". Unknown values enter at their expected value and the constraint is marked approximate; ordinal levels enter at the mean of the SMAA-O mapping (= equal steps). Weights are sampled by hit-and-run from an interior point found by linear programming; the output reports, per choice, the share of draws in which the drawn data still violate it. Results are reported with and without the choices (`ranking_autonomous`). Choices naming a hypothesis that is not ranked (filtered, not admitted) are listed in `expert_skipped`.
- **Contradictions**: `check_feasible` solves a linear program (strict choices need a positive margin); when no weights remain it returns a minimal conflicting set of choices (deletion filter). The pipeline then reports it as `criterion_gap` and ranks without the choices.
- **Which pair to ask next**: `next_pair` picks, among hypotheses with P(top-k) above the threshold, the pair with P(A > B) closest to 0.5.
- **Expert hypotheses** run through the same pipeline with origin "expert".

## Rules added on 2026-10-19 (spec sections 5–7, 9, 10)

- **Unknown stays unknown.** A qualifier the card leaves `unknown` gives `n/a` in the context match, never `no`; the verifier's "no" is overridden in code.
- **Inheritance from PICO** (narrowed on 2026-10-20, see above). Species, strain, sex, age at start and comparator could be copied from PICO into claims whose subject is the intervention, listed in `inherited_from_pico`; code marked a species the span does not name but PICO does, removed the mark when the span names the species, and rejected an unstated species in any other claim. A record that mismatches only an inherited value goes to `refusals` as `inherited_mismatch`: it sets no status (a mouse finding still does not support a claim inherited as human).
- **Contrast "mainly X, not Y".** The outcome is X with `qualifiers.contrast`; Y is a declared alternative with `stated_as: rejected` (claim-like, verbatim span), searched for and checked like a claim. The outcome status follows the table of spec 7, computed in `rules.contrast_status`: X refuted or Y supported → refuted; Y contested → contested; Y refuted → X's status; X supported with Y unchecked → unverified with the flag `contrast_unchecked`; the inputs are kept on the claim (`contrast`). Y checked in another species does not decide X. Alternatives only listed by the text are kept and never scored.
- **Relation `slows_aging_in`** (intervention → organism; non-neoplastic age-related change).
- **Ex vivo ≠ in vivo** (code): an ex vivo or in vitro record does not count for a claim about an organism; for a claim without an organism it counts at the cells rung.
- **Organisms in the quote** (code): when the quote names organisms and the claim's organism is not among them, the species does not match, whatever the extractor said (a sentence on yeast, worms and flies was extracted as a mouse finding).
- **Search by the relation alone** ("rapamycin slows aging mice") when the object is not an organism: long object phrases often match nothing. This query finds Wilkinson 2012 (PMID 22587563) for example 3's alternative.
- **Cut-off replies.** Gemini stops in the middle of some verbatim quotes, at the same place on every attempt (most likely its recitation filter, not the token limit: the replies were 100–900 tokens). A cut-off reply is asked again; the complete records of a cut-off reply are kept; a reply with none goes to the verifier of another family.

## Check against the worked examples (2026-10-19, after the rules above)

The raw texts of the card-spec examples run through the whole pipeline (normalizer and verifier on cheap models; the examples' expected cards and verified layers are in `tests/fixtures/cards`). Five runs while the rules above were added, 23–31 model calls each; the table gives the last run (`runs/v2_spec9.json`) and what varied.

| Example | Expected (spec) | Pipeline |
|---|---|---|
| 1. Low-dose rapamycin, human healthspan | mammals · replicated · ITP positive · mechanism partial · human_markers contested · next: trial with pre-registered primary outcome | the same. Earlier runs lost PEARL (PMID 40188830) to a cut-off reply (now: another family), and gpt-5-nano once took "mTORC1 inhibitors increase pain" as refuting "rapamycin inhibits mTORC1" (now: the stance rule in `verify_claim/v3`) |
| 2. D+Q, physical function | mammals (analog in aged mice) · single · partial | mammals · **replicated** (a second independent mouse study, PMID 25754370) · partial or unverified (whether "SASP drives physical decline" finds a finding varies). c2 and c3 inherit "human": mouse findings land in refusals as `inherited_mismatch`, the ex vivo explant finding no longer counts |
| 3. Rapamycin mainly via cancer, not aging | filtered: Y supported by PMID 22587563 → outcome refuted | the card has the expected structure in all five runs, and the search for Y finds PMID 22587563 every time. But the verifier also finds **Neff et al. 2013 (PMID 23863708)**: "our data largely dissociate rapamycin's longevity effects from effects on aging itself". So Y is **contested**, and by the table the outcome is contested (three runs). In the last run the outcome is **refuted** and filtered through X: the verifier counted "Disease patterns of rapamycin-treated mice did not differ from those of control mice" (PMID 19587680) against X; the reference reads it as "does not support", i.e. X unverified |
| 4. "Senolytics slow aging" | needs refinement (population, endpoint) | the same |
| 5. "Senescent cells are bad for health" | not a hypothesis | the same |
| 6. Resveratrol from middle age, mouse lifespan (comparator now unknown) | filtered (refuted) | the same: DrugAge records of the two ITP papers (PMID 20974732, 22451473). One run was contested: gpt-5-nano extracted Baur et al. 2006's sentence on yeast, worms and flies as a mouse finding (now: organisms in the quote) |

**What stage B took** (first check, before the rules above):
- **Normalizer.** A worked example in the prompt (on metformin, deliberately not one of the fixtures), rules for mechanistic hypotheses, and "aging" and "health" as non-measurable endpoints. Also a stronger model: gemini-3.5-flash split example 3 correctly, while gpt-5-nano, gemini-3.1-flash-lite and gpt-5-mini kept the premise as the outcome.
- **Verifier.** Rules for negative claims and for primary versus secondary or subgroup outcomes (`verify_claim/v2`); the analog probes in mice; a third search query.
- **DrugAge.** A paper counts against a lifespan claim only if neither average nor maximum lifespan rose significantly. PMID 22107964 is listed with a non-significant mean, but the paper reports longer survival of the last survivors.

**Departures from the reference to decide** (status 2026-10-21: all resolved — 1 by adding Neff 2013 to the reference, Example 3 contested; 2–4 by the spec update of 2026-10-20; 5 by the `other` rule of 2026-10-21):
1. Example 3: the reference expects Y supported; the literature found by the verifier has Y contested (Wilkinson 2012 vs Neff 2013), which makes the outcome contested by the contrast table. Either the reference adds Neff 2013, or the table needs a rule for this case.
2. Example 3's alternative a1 carries `species: mouse` that the span ("not by slowing aging itself") does not state; the reference leaves a1 without `inherited_from_pico` (c2 next to it has it). Our fixture marks it.
3. Admission of mechanistic hypotheses (spec 4a) asks for "≥1 mechanism claim"; with the contrast form the explanation is the outcome claim, so the outcome claim counts as the mechanism.
4. Example 1's c2 (the normalizer now writes `rapamycin slows_aging_in older adults`): the population sits in the object, not a qualifier; inheritance into the object is not covered by spec 9.
5. Claims with relation `other` get the status `unresolved` (spec 5: ignored by symbolic checks).

## Validation with DeepSeek V4.1 Flash as the verifier (2026-10-20)

`configs/v2-flash.yaml`: verifier `deepseek-v4.1-flash-1017` (the 2026-10-17 snapshot, pinned) without thinking; normalizer unchanged (gemini-3.5-flash). Through CometAPI the model with thinking spent the whole output budget (6,000 of 6,000 tokens) on hidden reasoning in about half of the calls and returned nothing; neither `reasoning_effort` nor a token budget is honoured, and our logs had counted only the visible output. With `extra_body: {thinking: {type: disabled}}` a verifier call takes about 5 s and 800–900 output tokens. Spent on the three runs below: about 190 Flash calls and 47 normalizer calls.

**Card-spec examples, same cards as the last Gemini run** (only the verifier differs): 16 calls, 42 s, no failures (with thinking: 80 calls, 60 failures, 15 min). Results as with Gemini, including example 3 contested by Neff et al. 2013. One error: in example 1 "Rapamycin is widely used as a complete inhibitor of mTORC1" (background) was labelled a finding; with thinking it was labelled background. The run with thinking matched the reference on example 3 only because its search did not return Neff 2013.

**Negative-sampling test, six groups** (groups 1–5 on the earlier cards, group 6 normalized anew): AUC 0.69 [0.48, 0.89]; after two fixes found in this run and applied without model calls (`negatives v2-refresh`), hit@1 0.50, MRR 0.60, AUC 0.78 [0.59, 0.94]. The fixes were found on these data, so part of the gain is fitting; the evidence-based decisions (procaine, carbinoxamine, alpha-lipoic acid, prednisolone refuted by DrugAge; coenzyme Q10 after the fix) agree with the test's labels, the order among unverified items is still noise. The fixes:
- a record that the extractor called "exact" while its quote and title name neither the compound nor a synonym counts as a related compound (malate and oxaloacetate quoted for citrate, SkQ1 for coenzyme Q10);
- related compounds and classes no longer set a status (spec 8: they count only as analogs); before, the rules let them.

**ITP backtest (T = 2010-12-31, 47 compounds, 10 later positive):** AUC 0.70 [0.54, 0.84] over all items, 0.64 [0.37, 0.89] on the test split; precision in the top quarter 0.36 against a base rate of 0.21. The per-axis check (`backtest axes`, spec 8 validation) shows where it comes from:
- effect level, robustness, mechanism and the multi-site flag take one value for every item (nothing at the rung by 2010), so they carry no signal here;
- the signal is translational distance (AUC 0.72) and novelty (0.62). Translational distance is ChEMBL's **current** max phase: a leak from the future in a backtest (drugs approved after T). Proposed: in a run with `as_of`, phase 4 only if ChEMBL's first approval year is before T, else unknown.

Two data problems found:
- **the pool is stale:** resveratrol and simvastatin are filtered by their own ITP paper (PMID 20974732, online October 2010, before T). The pool was built before the cut-off moved to the earliest date (online, print, PubMed entry), so these compounds should not be in it; rebuild with `backtest build-itp`;
- **strain is not checked:** every pool hypothesis names UM-HET3 mice (the normalizer puts it into qualifiers), but the DrugAge rule checks only the species and the verifier's prompt has no strain field. Earlier positive studies in other strains (2,4-dinitrophenol 2008, green tea extract 2007, metformin in SHR and HER2/neu mice) made three later ITP negatives known results. Whether evidence in another strain of the same species should count for a strain-specific claim, or only as an analog, is a specification question.

Status 2026-10-20: the strain question is decided (strain rule above); translational distance is replaced by `path_to_human` computed as of T; the pool is rebuilt (one test per compound and regimen, 70 tests, three labels). The backtest has not been re-run.

## Stage 4, historical backtest T = 2010-12-31, dev half (2026-10-21)

`backtest v2 --split dev` on the rebuilt pool (34 tests: 13 positive, 21 no effect), verifier DeepSeek V4.1 Flash,
normalizer Gemini, profile evidence_first; runs/stage4/itp2010_dev.json. 110 calls, no failures, 18 min. Date audit:
27 PubMed records, none after T. Outcomes: 31 ranked, 2 known results (rapamycin 4.7 and 42 ppm from 9 months:
the 2009 ITP paper), 1 filtered (resveratrol 300 ppm by its 2010 ITP paper, PMID 20974732).

| Cut | AUC | positives / negatives |
|---|---|---|
| all items (known results at the top) | 0.83 [0.67, 0.94] | 13 / 21 |
| known results left out | 0.80 | 11 / 21 |
| per compound (mean score), all | 0.83 | 7 / 21 |
| per compound, known results left out | 0.80 | 6 / 21 |

Precision in the top quarter 0.75 against a base rate of 0.38.

Per axis (dev, `backtest axes`): path_to_human 0.74 [0.62, 0.86], late_start 0.64 [0.44, 0.82], multi_site_positive
0.59, effect_level 0.54; robustness and mechanism take one value for every item, novelty 0.50.

Reading:
- The literature before 2010 is thin for these compounds (27 records for 34 tests): evidence moves only
  nordihydroguaiaretic acid (mammals, from the 2008 ITP paper) and rapamycin (known result). The ranking comes
  mostly from the priors `path_to_human` and `late_start`.
- `late_start` may carry the ITP's later design: the late-start regimens (17α-estradiol from 20 months, acarbose
  and canagliflozin from 16 months) are retests that the ITP chose after these compounds had worked from an
  early start, after T. The start age is in the hypothesis text, so the indicator can read that decision.
- Known results at the top of the ranking are not predictions; whether they stay in the metric is open.
- Several regimens of one compound are correlated items; the per-compound cut gives the same AUC here.

**Ablation on the dev half** (`backtest ablate`: the saved indicators re-aggregated without some axes, no model
calls; dropping nothing reproduces the run):

| Without | AUC, items [95% CI] | items, known results left out | compounds, known results left out | precision top quarter |
|---|---|---|---|---|
| nothing | 0.83 [0.67, 0.94] | 0.80 | 0.80 | 0.75 |
| late_start | 0.63 [0.42, 0.81] | 0.57 | 0.53 | 0.50 |
| path_to_human | 0.74 [0.55, 0.88] | 0.69 | 0.71 | 0.62 |
| both | 0.68 [0.49, 0.86] | 0.62 | 0.60 | 0.62 |

Most of the AUC rests on `late_start`, the axis suspected of reading the ITP's later choice of late-start
retests; without it and without known results the ranking of compounds is near chance (0.53). That both
dropped gives more than `late_start` dropped alone is within the noise of 13 positives.

**Protocol for the test half (agreed 2026-10-21, fixed before the run).** Primary metric (`backtest primary`): AUC
per compound (the mean score over its regimens; positive if any regimen is), on the ranking without
`late_start`, with known results left out and listed apart. Secondary: AUC per regimen on the same ranking; the
full ranking with `late_start` is reported for reference only. Run: `backtest v2 --split test`, same config,
verifier and profile as the dev half. On the dev half the primary metric is 0.53 [0.29, 0.77] (6 positive, 21
negative compounds), per regimen 0.57 [0.35, 0.76]. Outside the backtest `late_start` stays: in fresh hypotheses
the start age is the author's choice, not the ITP's later one.

**Test half (2026-10-21; runs/stage4/itp2010_test.json).** 36 tests, 126 calls, no failures, 23 min; date audit:
47 PubMed records, none after T. Outcomes: 34 ranked, 2 known results (rapamycin), nothing filtered.

| Metric | Test half | Dev half |
|---|---|---|
| **primary: per compound, without late_start, known results apart** | **0.73 [0.53, 0.89]** (10 / 22) | 0.53 [0.29, 0.77] (6 / 21) |
| per regimen, same ranking | 0.70 [0.52, 0.86] (12 / 22) | 0.57 [0.35, 0.76] |
| reference: full ranking with late_start and known results | 0.77 [0.60, 0.91] | 0.83 [0.67, 0.94] |

Where the test-half AUC comes from (per compound, without late_start):
- the top: rapamycin (one regimen ranked, replicated mammalian evidence before T) and nordihydroguaiaretic acid
  (the 2008 ITP paper), both positive; metformin third (mammalian evidence before T), negative;
- the bottom: five compounds with no path to humans (`path_to_human` level 2: β-guanidinopropionic acid, MIF098,
  ursolic acid, syringaresinol, fisetin) and four with novelty "analog", all negative;
- the 23 compounds between are tied within the Monte Carlo error of the expected value (half-width 0.01): their
  order is noise.

Reading: the signal is real but small and unstable between the halves (0.53 and 0.73, intervals overlapping
widely); it comes from pre-T evidence for two or three compounds and from the prior that compounds without a
path to humans fail more often. The halves are split by regimen, so compounds tested in several regimens
(acarbose, rapamycin, 17α-estradiol, canagliflozin, nordihydroguaiaretic acid) appear in both; only the metric
was chosen on the dev half. `both_sexes` (AUC 1.00) and `effect_size` (0.00) have a value for one positive and one
negative only.

## Охват по полу и страты протокола (2026-10-22, после первого прогона бэктеста)

Дефект, найденный на карточке NDGA: гипотеза шаблона «extends the median lifespan … of at least one sex» была «оспорена»
нулевым результатом у самок (ITP 2010), хотя у самцов эффект подтверждён (ITP 2008). Правило не вшито в проверку, а
вынесено в поле карточки:

- `Claim.sex_scope` (`any` | `unspecified`): нормализатор (шаблон `normalize_card/v5`) записывает `any` из слов текста
  «at least one sex» / «either sex»; код выставляет его так же, если модель поле пропустила (`rules.set_sex_scope`).
- `rules.scoped_against`: при `any` нулевой результат у одного пола не считается «против», если у этого пола нет поддержки
  и нулевые результаты не покрывают оба пола; снижение продолжительности жизни, нулевой результат у того же пола и
  нулевой результат в целой выборке считаются. Запись остаётся в карточке (флаг `other_sex_null`), учитывается
  `both_sexes` и альтернативой `sex_specific`. Без `sex_scope` статус не меняется; причина `sex_conflict`.
- `EvidenceRecord.strata`: пол в ITP и CITP задан протоколом заранее; `rules.mark_strata` ставит `strata: [sex]` на строки
  DrugAge программы и записи PubMed тех же работ, берёт неизвестный пол записи из курируемой строки той же работы,
  `subgroup_only` для таких записей не ставится (апостериорные подгруппы остаются `subgroup_only`).
- Пересчёт сохранённых прогонов: `python -m hyparena.backtest reapply --v2 … --out …` (`--legacy` воспроизводит прежний
  прогон; тест `test_reapplying_the_old_rules_reproduces_a_saved_run`). Модели не вызываются.

Результат на ITP 2010 (подробно в «Справочнике → Данные и источники»): статус изменился у четырёх режимов (аспирин
200 ppm, NDGA 800, 2500 и 5000 ppm: оспорено → подтверждено → известный результат, вне рейтинга); AUC с ничьёй по
рейтингам половин: dev 0.68 → 0.62, test 0.74 → 0.72. Попутно найдено: AUC без ничьей зависит от seed (внутри группы
«на равных» порядок случаен), поэтому добавлены `backtest.tied_auc` и `primary_tied`. Открыто: дозы курируемых
записей не сравниваются с дозой гипотезы (NDGA 800 и 5000 ppm стали «известными» из работы при 2500 ppm). По этой
выборке правила больше не менять.

## Контекст «модель болезни» (2026-10-22, после первого прогона бэктеста)

Дефект, найденный на Minocycline: пять записей из моделей БАС и мышечной дистрофии задавали статус «оспорено» утверждению про
обычных мышей, а записи Lovaza на линии NZB/W F1 (волчаночная) давали «известный результат». Исправлено через соответствие
контекста, а не флагом доверия:

- `rules.claim_disease`: для утверждений о продолжительности жизни, здоровье и старении неуказанная болезнь значит «не
  модель болезни» (правило по типу исхода, не по модели); болезнь утверждения: `qualifiers.disease` или болезнь, названная в
  описании популяции.
- `rules.disease_match` и `rules.add_disease_analogs`: запись из модели болезни (валидная метка: название болезни и место, где
  оно названо) не задаёт статус; уходит в аналог `an<N>` («модели болезней»), у утверждения отказ `population_mismatch`.
  Утверждение про болезнь: болезнь должна совпасть (`contexts.same_disease`). `aging_model`: пока не засчитывается.
  Эксперт возвращает запись решением `disease_context`/`restore`. Шаг обратим (`undo_disease_analogs`).
- Профиль: записи моделей болезней не входят в `effect_level` и `path_to_human` (поле профиля `disease_models`, строка «модели
  болезней: N записей» вместо подписи «только модели болезней»); питают `disease_specific` и `disease_proxy`.
  Аналоги моделей болезней не дают и новизну `analog` / `translation`.
- `contexts.flag`: метка `disease_model` ставится вместе с `disease` и `disease_evidence`; в таблицу добавлены мутанты SOD1
  (G37R, G85R, …), нокаут ламинина-α2, GLD. Флаг без названия болезни не действует.
- Пересчёт сохранённых прогонов: `backtest reapply` (карточки, записи и модели не трогаются; аннотации из кэша PubMed).

На ITP 2010 правило не изменило ни одного статуса и ни одного исхода (аналог получили 11 режимов, статусы держались на записях
об обычных мышах); у двух режимов половины test (Minocycline 300 ppm, микофеноловая кислота) новизна `analog` стала `new_link`,
потому что их «аналог» состоял из записей моделей болезней. В примере на мышах: Minocycline «оспорено» → «не проверено»,
оба Lovaza «известный результат» → в рейтинге. Таблица по каждому режиму: `docs/itp_2010_changes_after_first_run.csv`.

## Золотой снимок и защита по дате (2026-10-23, по плану тестов)

- **E1, снимок бэктеста.** `tests/fixtures/itp2010_snapshot.csv` — 70 строк: статус основного утверждения, место в профиле
  `evidence_first`, ожидание и P(топ-3) по объединённому рейтингу на 2010-12-31. Строится из сохранённых прогонов без
  вызовов моделей: `python -m hyparena.snapshot` (запись), `--check` (сверка). Тест сверяет снимок со списком
  `docs/itp_2010_changes_after_first_run.csv`: статус, исход и место должны совпадать, поэтому любое изменение снимка
  требует строки в списке «изменения после первого прогона». Если прогонов нет в рабочей копии, сверка с ними
  пропускается, остальные проверки работают.
- **D1, дата у каждого источника.** `verifier.date_guard`: после поиска и до чтения резюме каждый PMID датируется самой
  ранней публичной датой PubMed; позже T или без даты — отбрасывается и записывается в журнал поиска
  (`date_guard_dropped`). Раньше фильтр стоял только в запросе к PubMed, а источники от эксперта (`expert_pmids`) его
  обходили. Те же правила для поиска по альтернативам. Даты кэшируются в `data/cache/pubdates.json`.
- **D2, аудит.** `backtest audit` теперь перечисляет записи, которые нельзя датировать (`undated`, `undatable`);
  `audit --final` падает, если такие есть (финальный прогон на дату T), без флага это предупреждение. Сохранённые
  прогоны ITP dev и test проходят строгий аудит: 27 и 47 записей, недатированных нет, после T нет.

## Спецификация до данных (2026-10-23, тест A4)

- **Файлы:** `specs/evolution-1.yaml` (критерий и параметры эволюции) и `specs/itp-backtest-2010.yaml` (дата T, профиль,
  исключённые показатели, главная метрика и правило «на равных» для выборки ITP). Тест `test_spec_files_say_what_the_code_does`
  сверяет их с кодом: параметры, значения по умолчанию и `PRIMARY_DROP` не могут разойтись со спецификацией.
- **Запуск со спецификацией:** `--spec specs/…yaml` у `hyparena.card.pipeline`, `hyparena.backtest v2` и `hyparena.card.evolve`.
  Спецификация должна быть закоммичена и без правок (иначе запуск не начинается), параметры запуска должны совпадать с её
  параметрами (иначе тоже). В мету пишется `meta.spec`: файл, хэш содержимого (по разобранному YAML, комментарии и порядок
  ключей не влияют), коммит, время коммита и время метки в UTC; метка ставится до чтения данных.
- **Проверка:** `python -m hyparena.prespec check runs/….json` пересчитывает хэш по коммиту, проверяет, что коммит в истории
  и старше метки; `tests/test_prespec.py` делает это на временном репозитории.
- **Что это доказывает и чего нет.** Порядок «спецификация в git, затем запуск». Не доказывает, что спецификацию не писали,
  уже видя данные где-то ещё, и не охватывает прогоны до 2026-10-23: у них нет `meta.spec`. Для первого прогона эволюции
  порядок подтверждается только историей git (протокол в `docs/evolution-experiment.md` закоммичен в `f3ba37a`, 2026-10-22
  14:49 UTC, результат в `4aa2e6b`, 15:04); `specs/evolution-1.yaml` записывает его машинно после факта и на тот прогон не
  ссылается. Выборка ITP: первый прогон сделан до этого механизма, любой новый прогон на ней идёт по `specs/itp-backtest-2010.yaml`.

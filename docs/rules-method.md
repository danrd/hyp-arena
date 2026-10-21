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
| Card-based proximity (spec 8b): duplicate, variant, competitor, contradiction, analog (shared ChEMBL mechanism target), mechanism neighbour (shared hallmark or molecular node); duplicates are not verified twice, competitors become alternatives | code: `hyparena/card/proximity.py` | done (no embeddings fallback, no ChEBI classes, refinement siblings not linked) |
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
- **Human rungs.** Evidence records carry `human_rungs` (markers: laboratory and instrumental measures; clinical: function, frailty, pain, disease, mortality); a human claim has a status per rung (`rung_status`). Subgroup rule: when all support is subgroup-only and the claim has admissible counterevidence, the rung is contested and the conflict lists that counterevidence.
- **Strain rule.** The card's strain unspecified → `n/a`. Specified and different → the record moves to an analog `an<N>` (same intervention and species, other strain): it counts for the effect level, not for the known result, and novelty becomes `new_context`. An inherited strain that differs also leaves an `inherited_mismatch` refusal. Code sets `qualifiers_match.strain` (left out when the record reports no strain); "genetically heterogeneous" matches UM-HET3 and outbred stocks.
- **Evidence records.** `sex` (male, female, both, unknown), `strain`, `dose`, `age_at_start` from the verifier (v5: keys the abstract does not report are left out, not guessed) and from DrugAge (one record per paper and strain). Curated `intervention_match` by field rules: the card's route differs from the record's (ppm in food = diet, in drinking water = water) or the card is intermittent and the record continuous → `regimen_differs`; `dose_differs` only from the model.
- **gate_reason.** The refuting record ("PMID:20974732", program records first) or "contrast rule: a1 supported (PMID:22587563)".
- **path_to_human** replaces cost, time and translational distance: preliminary steps before a human trial with marker or function endpoints — a preclinical safety package when there are no human safety data (approved drug, clinical-stage compound or diet count), a mouse study when there is no supported mammalian effect; 0 · 1 · 2, a gene without a drug unknown. As of T: approved if ChEMBL's first approval year ≤ the year of T, clinical stage if ClinicalTrials.gov has a trial with the compound started before T (`hyparena/tools/trials.py`; its intervention search can over-match names). `next_step` stays outside the ranking.
- **Novelty levels** new_context < translation < analog < new_link; `both_sexes` from the records' `sex`; SMAA-O is the default ordinal mapping.
- **Alternatives (spec 8c).** Ids a<N> declared, alt<N> pipeline, an<N> analogs. The checklist rows are included by rules over card and record fields; one call per gate-passing hypothesis over the abstracts the verifier already read: an abstract with the discriminating control and the effect persisting → `excluded_by_evidence` with a verbatim quote; with the effect gone → `supported` (our addition: the spec has only excluded and open); else `open`. A dedicated search per open row only when P(top-k) ≥ 0.5 in some profile. Informativeness stays unknown until stage C.

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
| analog | other interventions with a shared mechanism target (rapamycin, everolimus, temsirolimus: FKBP1A) |
| mechanism_neighbour | other interventions acting on the same hallmark or molecular node (both "inhibit mTORC1") |

A pair can carry several types (a competitor in another context is also a variant; opposite mechanism claims
under the same outcome are a contradiction and competitors). Pairs come from buckets (same intervention,
triple, target, node), so a pool of thousands of cards is cheap. In the pipeline: a duplicate of an earlier card
gets the outcome `duplicate` with `duplicate_of`, is not verified and takes the score of the card it duplicates
in the ladder format (`dedup=False` turns this off); competitors are added to each other's alternatives row
(`source: proximity`, `ref`); the result lists all relations (`proximity`) and the groups of variants.
Not done: the embedding fallback for unresolved entities, the ChEBI class hierarchy for `analog`, refinement
siblings (`parent_id`), novelty against a knowledge graph.

## Spec decisions of 2026-10-21 in the code

- **Contrast on a split literature (Example 3).** Neff et al. 2013 (PMID 23863708) is counterevidence to the rejected alternative a1 next to Wilkinson et al. 2012: a1 contested → the outcome contested by the table, `gate: pass`. The row "Y supported → outcome refuted" is a synthetic test (Example 3 without Neff 2013).
- **Searching Y in both directions.** The first query of every claim excludes reviews (`... NOT review[pt]`): reviews only give background, never a status, and push findings out of the first page. PubMed's relevance order drifts: on 2026-10-19 "rapamycin slows aging mice" returned Neff 2013 in the top 8, on 2026-10-21 only in the top 20; without reviews both studies are in the top 8. A rejected alternative is searched with 12 abstracts instead of 8, and the verifier prompt asks for findings on both sides, from every abstract. When the object of a claim is an organism, its `measure` is also a query. `verify_claim/v5` was amended in place (it had not run on a model).
- **`other` on the outcome claim.** The normalizer re-parses once with a hint naming the nearest vocabulary relations (word overlap of the claim's note and span with cue words per relation); still `other` → admission flag `unmapped_relation`, outcome `unparsed`, listed in `unparsed` with the note. `normalize_card/v4` gained the hint block (it had not run on a model either).
- **Nothing disappears silently.** Every input ends with exactly one outcome (ranked, filtered, known_result, needs_refinement, not_a_hypothesis, unparsed, normalization_failed); the result lists `awaiting_refinement` (with `missing_critical`), `unparsed`, `directions`, `normalization_failed`, and reports `outcome_counts` and `outcome_shares`. Refined variants are not generated yet.
- **`late_start`** (`hyparena/card/lifespan.py`): an exact age ("600 days", "20 months", "18-20 months") over the median lifespan of the species (most specific entry: species + strain + sex, + strain, + sex, species), capped at 1; a verbal age gives an interval from a per-species table; otherwise unknown. The aggregation draws an interval uniformly within it (`aspid.cardinal_range`); an expert choice takes its midpoint and is marked approximate. The tables (`configs/lifespan_medians.yaml`) have no values yet, so late_start is still unknown everywhere.

## Lifespan stance by code, context flags (2026-10-20)

Two error types seen in the negative-sampling run (`docs/negative-sampling.md`, section 6):
- **Stance of lifespan findings.** The verifier (`verify_claim/v4`) extracts the direction of a lifespan finding (increase, decrease, no effect); code sets the stance from it, as for DrugAge: a finding supports the claim whose direction it matches (extends ↔ increase, shortens ↔ decrease, no effect or a negated "extends" ↔ no effect) and counts against the others. When the extractor's own stance differs, the record notes it. Before, gpt-5-nano took "Lovaza extends life span" as support for "Lovaza shortens lifespan".
- **Disease models and special conditions** (`configs/disease_models.yaml`, `hyparena/card/contexts.py`): which strain or diet a study used is in the text; what it means is a lookup. A seed table of about 30 models (lupus-prone, cancer-prone, metabolic, neurodegeneration, progeroid and senescence-accelerated strains, short-lived worm mutants, high-calorie diets) is matched against the record's abstract and DrugAge's strain field; a match adds the flag `disease_model`, `short_lived_controls` or `special_diet` with the model's name. Flags do not change a status (spec 7); the profile reports e.g. "mammals (disease models or special conditions only)" when every record at the effect level is flagged. The table is a stand-in until a strain ontology is part of the knowledge graph.

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

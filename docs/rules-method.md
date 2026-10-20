# Our method, version 2: verified card → rule-based indicators → aggregation

Design decided in the working notes on 2026-10-19 (sections 2.1–2.4); specifications in `docs/spec/`
into `docs/spec/` (card format, worked examples, aggregation). The LLM tournament over the whole pool (ladder
step L4) is kept as an intermediate step for comparison; the two Co-Scientist baselines (L0, L0ts) keep their
tournaments. The 2026 baseline's plagiarism penalty and claim-versus-log checks are not reproduced: both act on
generated ideas and manuscripts, and external hypotheses have no experiment logs (decision 2026-10-19).

| Step | Who | Status |
|---|---|---|
| Normalizer: text → declared card (claims in a closed vocabulary, each with a verbatim `source_span`; qualifiers inherited from PICO marked; contrast "mainly X, not Y" as outcome X plus a rejected alternative Y) | LLM (`normalize_card/v3`, gemini-3.5-flash), code marks unmarked species inheritance, validates and asks again: `hyparena/card/normalizer.py` | done |
| Compound identifiers: interventions typed as compounds → PubChem parent compound, ChEBI, ChEMBL, max clinical phase, synonyms | code: `hyparena/tools/compounds.py`, `hyparena/card/entities.py`; DrugAge names mapped once in `data/drugage_compounds.json` | done (compounds only) |
| Validation and admission (accepted / needs refinement / not a hypothesis) | code: `hyparena/card/rules.py` | done |
| Verifier: evidence records with verbatim quotes, quote role, context match, endpoint; rejected alternatives checked like claims; analog probes in mice for human outcomes | DrugAge (curated, deterministic) + PubMed abstracts (LLM extracts with `verify_claim/v3`; code drops quotes that are not verbatim and checks the context, see below): `hyparena/card/verifier.py` | done |
| Claim statuses (with the contrast rule), gate, evidence profile, next step, known result | code: `hyparena/card/rules.py` | done |
| Indicators (spec 8a) | code: `hyparena/card/indicators.py` | done for evidence-based ones; cost, time, late start and informativeness stay unknown until their inputs exist |
| Aggregation under preference profiles (МРСП / SMAA-2) | code: `hyparena/aspid.py`, profiles in `configs/profiles.yaml` | done |
| Ranking across profiles, robust candidates | code: `hyparena/card/rank.py` | done |
| End to end | `python -m hyparena.card.pipeline --paste file.txt --out result.json` (`configs/v2.yaml`, `--fake` for no model calls) | done |
| Expert layer (card spec 7a; Aggregation_Spec 6a): sources sent through the verifier, opinions kept apart, pairwise choices as weight constraints, the expert's own hypotheses | `hyparena/card/expert.py`, `Prefer` / `check_feasible` / `next_pair` in `hyparena/aspid.py`; `--expert expert.yaml` | done (file input; no interface yet) |
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

## Compound identifiers (2026-10-20)

After normalization, every intervention the normalizer typed as a compound is looked up in PubChem by name and mapped to its parent compound, so salts, hydrates and synonyms collapse (sirolimus = rapamycin, quercetin dihydrate = quercetin, 17‐α‐estradiol with any dash). From the parent: the preferred name, InChIKey, the ChEBI id (listed among PubChem's synonyms), the ChEMBL id and maximum clinical phase (ChEMBL, by InChIKey). The card gets `Intervention.id` (ChEBI, else `PubChem:<CID>`); a claim's subject gets an id only when every part of it is one of the card's compounds by name or synonym (a combination: "CHEBI:a+CHEBI:b"). Other subjects are never looked up: "SASP" is also a synonym of sulfasalazine.

Uses:
- "the same intervention" (effect level, novelty, inheritance) compares identifier sets when both sides have them, names otherwise;
- DrugAge rows match the claim's compound by parent CID (all 1,046 DrugAge names mapped once), by name when a name does not map;
- translational distance takes ChEMBL's max phase of the resolved compound (a compound in ChEMBL without a phase counts as preclinical); before, the phase came from a fuzzy name search in Open Targets, which always returns some best match.

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
- **Inheritance from PICO.** Species, strain, sex, age at start and comparator may be copied from PICO into claims whose subject is the intervention; they are listed in `inherited_from_pico`. Code marks a species the span does not name but PICO does (normalizers often copy it without the mark), removes the mark when the span names the species, and rejects an unstated species in any other claim. A record that mismatches only an inherited value goes to `refusals` as `inherited_mismatch`: it sets no status (a mouse finding still does not support a claim inherited as human).
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

**Departures from the reference to decide:**
1. Example 3: the reference expects Y supported; the literature found by the verifier has Y contested (Wilkinson 2012 vs Neff 2013), which makes the outcome contested by the contrast table. Either the reference adds Neff 2013, or the table needs a rule for this case.
2. Example 3's alternative a1 carries `species: mouse` that the span ("not by slowing aging itself") does not state; the reference leaves a1 without `inherited_from_pico` (c2 next to it has it). Our fixture marks it.
3. Admission of mechanistic hypotheses (spec 4a) asks for "≥1 mechanism claim"; with the contrast form the explanation is the outcome claim, so the outcome claim counts as the mechanism.
4. Example 1's c2 (the normalizer now writes `rapamycin slows_aging_in older adults`): the population sits in the object, not a qualifier; inheritance into the object is not covered by spec 9.
5. Claims with relation `other` get the status `unresolved` (spec 5: ignored by symbolic checks).

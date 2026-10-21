# hyp-arena: design notes (interim)

> Interim snapshot of design decisions and open points. Not final. Companion notes: [data sources](data-sources.md) (sources, formats, live checks), the knowledge-graph design (own KG design).
> Last updated: 2026-10-19.

---

## 1. Task framing (agreed)

- Goal: a **hypothesis evaluation and comparison loop**, "like Google Co-Scientist but better in a specific respect".
- Hypotheses arrive **from outside** (LLMs generate them in volume). The task is to decide which are promising; **generation and supervisor are stubs**. Review and ranking are replaced by verification, rule-based indicators and АСПИД (section 2); evolution is an objection-directed loop (section 2.4); Proximity is typed and computed from the card (spec 8b; since 2026-10-19).
- Honest claim we can make: "our selector picks better from a given pool", not "a better system overall" (Co-Scientist also gains from the rank → evolution feedback loop).
- Co-Scientist is **not a SOTA** for this narrow task: no common benchmark for selecting externally given hypotheses by promise (in the open literature searched, mostly arXiv; biomedical and closed sources not covered). Use it as a baseline and design source. Its code is not public, so baselines are our own reimplementations, flagged as such. **Two baseline variants are compared** (decided 2026-10-15): (a) the 2025 design — Reflection + Elo tournament via debates; (b) the 2026 version (`2608.26701`) — TrueSkill + UCB ranking with plagiarism penalty and claim-vs-log checks.
- "Better" must be defined by numbers: agreement with an independent signal at equal LLM budget (tokens, calls reported too); budget efficiency; robustness to position/style bias; honest uncertainty (rank intervals); per-indicator values instead of one Elo.
- Hidden holdout is mandatory (AIRA² HCE idea): selector and judge never see labels or self-report scores.

## 1a. Ground truth and model budget (2026-10-14)

- **No expert labels assumed.** Expert preference data is a bonus (an optional top validation tier), not a foundation. Ground truth must come from non-human sources: time-split backtest on literature, replication outcomes (ITP, CITP; DrugAge for pre-T history only, item A2), trial registry outcomes/durations.
- Still report cost per run and compare against the baseline at **equal budget**; "no budget limit" does not remove the need for a fair comparison.
- RPM evidence (read): selection accuracy grew with reasoning budget, with context depth and with ensembling (offline pairwise: majority of three frontier models 68.0%, arbiter 69.4%), so spending on stronger judges is justified, but gains were modest.
- Without human labels, **agreement between LLM judges is not validity**. Judge quality must be checked by (a) position-swap consistency, (b) cross-family agreement as a sanity check only, (c) accuracy on backtest labels (does the ranking put historically confirmed hypotheses above those that failed, using only pre-cutoff information; since 2026-10-19 the ranking is АСПИД over rule-based indicators, and the effect of debates is measured by ablation), (d) sensitivity to style (same content, different phrasing/format).

## 2. The core scientific question: approximating "promise"

- No direct criterion: aging outcomes are slow and surrogate markers (epigenetic clocks) are contested. Treat promise as a **latent variable** approximated by several proxies of different cost/validity; **validating the proxies is the scientific part**.
- **Criteria set** (history; resolved 2026-10-19 by the rule-based indicators in [card spec, section 8a. Scoring indicators for АСПИД (draft, 2026-10-19)](hypothesis-card-spec.md) and the evidence profile, which replaced S0–S5). Was an open question. Earlier draft proxy families: evidence support; novelty/neglectedness; testability and cost; value of information; fit to hallmarks; expert preference. A later draft proposed five axes: support, novelty, gain if true (ladder steps S0–S5 + hallmarks), testability (cost/time of the decisive experiment, falsifiable implications), informativeness (value of information: does the test discriminate between competing explanations, e.g. "rapamycin extends lifespan mainly via fewer senescent cells vs via delayed cancer"). Informativeness is the hardest to measure at scale; options: binary proxy ("discriminates ≥2 explanations from the literature") or leave out of the MVP. Either few or many criteria, not a hand-weighted middle.

### 2.1 Aggregation without explicit weights: АСПИД / МРСП (proposed, 2026-10-15)

Proposed method: **АСПИД** (analysis and synthesis of indicators under information deficit), by N. V. Hovanov (SPbU); its core is the **method of randomized aggregated indicators (МРСП)**. Confirmed by one source that МРСП is the basis of the АСПИД methodology and is used to evaluate complex objects with missing information on weights ([SPbU Economics](https://economicsjournal.spbu.ru/article/download/3890/3475/6285)). Method details below are from general knowledge — **verify against Hovanov's papers** before relying on them.

**Verification (second pass, 2026-10-19; secondary sources, Hovanov's monograph not read):** English references exist and were checked via Crossref: Hovanov, Kolari, Sokolov, "Deriving weights from general pairwise comparison matrices", *Mathematical Social Sciences* 2008 (doi:10.1016/j.mathsocsci.2007.07.006); Hovanov, Yudaeva, Hovanov, "Multicriteria estimation of probabilities on basis of expert non-numeric, non-exact and non-complete knowledge", *EJOR* 2009 (doi:10.1016/j.ejor.2007.11.018); monograph Хованов Н. В., «Анализ и синтез показателей при информационном дефиците» (1996); decision-support systems АСПИД-3W (Колесов, Михайлов, Хованов, СПбГУ, 2004) and APIS. In English the method is known as the aggregated indices randomization method (AIRM). Confirmed: ordinal and interval information as equalities/inequalities on weights; weight vector uniformly distributed on the admissible set; outputs = expected aggregated index and its spread; **dominance probability = share (measure) of admissible weight vectors under which A ≥ B**, plus probability of being best; hierarchical version (weights sampled per node); in practice a discrete weight grid with step h = 1/k and Monte Carlo sampling (worked example with k = 50 and 10⁷ samples, [nbpublish article 32328](https://nbpublish.com/library_read_article.php?id=32328)). In that example normalization is linear min–max over the compared objects; whether Hovanov's own normalization functions are nonlinear is not confirmed. Implementation notes (SMAA algorithms read in full, Hovanov's monograph not accessible): [aggregation spec](aggregation-spec.md). Caution for us: min–max over the pool makes every score depend on which hypotheses are in the pool (rank reversal when hypotheses are added, e.g. by the evolution loop); decided: fixed reference scales ([aggregation spec](aggregation-spec.md) section 2).

How it works:
1. Each indicator is normalized to [0, 1] by a function of a declared **type** (higher is better, lower is better, saturating, etc.).
2. Weights are not given as numbers. Only what is known is given: an **order of importance** ("support ≥ novelty"), possibly intervals; information may be non-numeric, inexact and incomplete.
3. The weight vector is treated as **random, uniformly distributed** over all weight vectors consistent with that information.
4. Output per object: **expected aggregated score**, its spread, and **probability that object A dominates object B**.

Why it fits:
- It is the rigorous version of "rank robustness to weights": instead of "stays on top under several reasonable profiles" → "probability A beats B over all weights consistent with the importance order" (computed per profile; robustness across profiles is kept, see below).
- Experts give only the order of importance, not numbers: simpler and more honest under expert scarcity.
- Many criteria become affordable (only ordinal information needed); hard-to-measure criteria can enter with weak information or be dropped without breaking the scheme. Answers the "few or many criteria" question in favour of many.
- Uncertainty is built in: dominance probabilities = the honest "rank with intervals".
- International analogues to cite alongside (checked later: SMAA implementation paper read in full, [aggregation spec](aggregation-spec.md)): SMAA (Stochastic Multicriteria Acceptability Analysis), rank-order centroid weights.

Integration:
1. Criteria = indicators with type and normalization function.
2. Values come from the pipeline: support from evidence records, novelty from the KG (same function as proximity, spec 8b), cost/time from reference classes; since 2026-10-19 all criteria are rule-based indicators over the verified card (spec 8a), no LLM scores criteria.
3. **Importance order = a parameter set together with experts** (goes into "parameters to discuss").
4. Output: expected score, spread, pairwise dominance probabilities → portfolio selection.
5. Placement: line 1 (ranking mechanism without explicit weights).
- Validation of proxies without ground truth "now": **time-split backtest** (HindSight idea: hypotheses before date T vs later literature), replication labels (multi-site programs ITP and CITP; DrugAge for pre-T history only, item A2), small expert-labelled set as top tier. Deliverable: a table "which cheap proxy predicts which expensive outcome", with intervals.
- Risks: Goodhart (select a portfolio, keep a hidden set), conformity bias of backtests, LLM pretraining leakage (use models with cutoff before T), citations lag/hype (APRES authors flag this).

**Importance order as a feature, not a limitation (2026-10-19).** The ordinal importance order is the place where the goal of whoever ranks enters: a set of premises and a filter. Examples of preference profiles: "cheap and feasible ideas with decent novelty" (path to humans ≥ novelty ≥ evidence level) vs "fundamental" (mechanism, informativeness, novelty ≥ cost). АСПИД gives a ranking per profile; hypotheses that stay on top across profiles are robust candidates, and profile-specific winners show what each goal would pick. Profiles are named, versioned inputs of a run (reported with results), not hidden weights.

### 2.2 Judge role and its link to АСПИД (agreed 2026-10-18)

Pipeline, in order (three steps, no final verdict call):
1. **Facts** (verifier and other agents): evidence profile, novelty via the KG (spec 8b), cost/time. Anything that needs computing or checking (e.g., plausibility of an `unverified` link) goes to a dedicated agent, never to the judge.
2. ~~**Judge, criterion mode:**~~ **Superseded 2026-10-19:** criteria are scored by rules from the verified card, not by an LLM judge (absolute LLM scores compress and drift; pairwise scoring would bring back a tournament). Draft indicator table: [card spec, section 8a. Scoring indicators for АСПИД (draft, 2026-10-19)](hypothesis-card-spec.md). All indicators are rules (some over the KG), informativeness too, via the prediction table in spec 8c; debates only add alternatives and discriminating designs. The judge's role: debates on strong hypotheses only (section 2.3, judge design).
3. **АСПИД** aggregates the indicators under random weights → expected score, spread, P(A beats B).

**No final verdict call (decided 2026-10-18).** The АСПИД output is the final ranking. Reasons: on pairs where АСПИД is confident a verdict would mostly copy it (LLMs anchor on shown numbers); on pairs where it is not, near-ties under all admissible weights are an honest result, broken without an LLM (expected score, cost, portfolio diversity); if something the criteria miss keeps showing up, the fix is a new criterion, not an extra call. Comparison with baselines stays rank-based (their output is an Elo/TrueSkill ranking). A verdict step on uncertain pairs is kept only as a possible later ablation.

The halo-effect concern (strong evidence inflating "gain if true") is moot after the 2026-10-19 change: "gain if true" is split into rule-based indicators (late start, both sexes, effect size; translational distance was one of them until 2026-10-20, now part of the path to humans, section 3).

### 2.3 Co-Scientist debates, and where we might need a judge (2026-10-19)

**How the 2025 Co-Scientist tournament works** (read in the paper `2502.18864`, Methods and Supplementary Notes 3, 9.3, 10.9):
- Ranking agent runs an Elo tournament; new hypotheses start at 1200.
- Pairing: hypotheses are more likely compared with similar ones (Proximity agent's graph); newer and top-ranked hypotheses are prioritized.
- **Top-ranked pairs: multi-turn "scientific debate"**; lower-ranked pairs: single-turn pairwise comparison. The debate is **one LLM call simulating a panel of experts**, not separate agents: input is the goal, criteria ("preferences"), both hypotheses and their initial Reflection reviews; 3–5 turns, max 10; ends with "better hypothesis: 1 or 2" and a rationale. The plain comparison prompt tells the model to ignore numeric review scores.
- Ablation: the debate prompt is more accurate on high-quality pairs (higher AUC on top-ranked ideas) and nearly removes the second-position advantage (2000 matches, AB vs BA).
- Elo validity was checked only indirectly: higher-Elo answers were more accurate on GPQA; the paper notes Elo is auto-evaluated, not ground truth.
- Debate transcripts feed the Meta-review agent (recurring weaknesses → feedback to other agents).

**2026 version** (`2608.26701`): pairwise LLM comparisons with rationales update TrueSkill ratings N(μ, σ²); UCB = μ + κσ (κ = 1) picks parents for evolution; Reflection critiques novelty, feasibility/plausibility, testability. Debates are not mentioned in the parts read.

**Candidate roles for a judge in our pipeline** (resolved below: A and B adopted, C as an ablation only; see the judge design):
- A. **Resolving contested evidence.** The profile deliberately records `conflicts` without a rule for which side wins. A debate between advocates holding the "for" and "against" records (study design, controls, flags), with a separate judge, is a judge's role in the classic sense. Output (as decided in the judge design): sustained objections become check requests to the verifier; a claim status changes only through verified evidence.
- B. **Informativeness.** Debate between competing hypotheses for the same phenomenon (Proximity-style pairing) whose output is a discriminating experiment, not a winner; adds alternatives and discriminating designs to the prediction table (informativeness itself is a rule, spec 8c).
- C. **Near-ties at the top of the АСПИД ranking.** Co-Scientist's own ablation says debate helps most on high-quality pairs; kept as an ablation only (the plain verdict call was dropped, section 2.2).
- **Pairing for debates is rule-based** (2026-10-19): A takes `contradiction` pairs and claims with `conflicts`, B takes `competitor` pairs, from the card-based proximity in [card spec, section 8b. Proximity from the card (agreed in principle, 2026-10-19)](hypothesis-card-spec.md). Proximity and novelty are one similarity function over cards (against the pool vs against KG `supported` edges); one more argument for our own KG.
- Implementation difference from Co-Scientist: real multi-agent debate (separate advocates with access to the evidence records, separate judge) instead of one simulated panel. Literature to check before relying on it: Du et al. `2305.14325` (multi-agent debate improves factuality and reasoning), Khan et al. `2402.06782` (debate helps a weaker judge reach truthful answers).

**Judge design, draft (agreed "as a start", 2026-10-19).** Judges see only strong hypotheses and produce full debates plus feedback for improvement.
- **Entry:** from the АСПИД draws, P(hypothesis in top-k); judges take those with P ≥ 0.5 (includes near-ties at the boundary). Gate already passed.
- **Format 1, prosecution vs defence on one hypothesis (includes role A):** the prosecutor builds the strongest case against: first `conflicts`, then the failure modes of section 6a (indirect route, genetic background, endpoint mismatch, correlation, translation), then competing explanations. The defender rebuts. Both work from evidence records and the KG, not free text; an argument without a record reference does not count. A separate judge rules on each objection: sustained / rejected / needs check.
- **Format 2, competitor pairs (role B):** only `competitor` pairs among strong hypotheses (`contradiction` pairs go to Format 1, role A) (rule-based pairing, spec 8b). Output: a discriminating experiment, not a winner.
- **Principle:** debates change the ranking only through facts and new variants, never through opinion; АСПИД stays the only aggregator.

| Debate output | Goes to | Effect |
|---|---|---|
| `check_request` (e.g., "is the effect explained by reduced food intake?") | verifier | new claim checked against evidence → card updated → АСПИД recomputed |
| `refinement` (sustained objection that can be fixed: narrower population, added control, both sexes) | refinement loop | new hypothesis, `origin: internal` + `parent_id`, full pipeline, may re-enter the top |
| `discriminating_experiment` | prediction table (spec 8c) | adds rows; informativeness recomputed by rule; cost via reference classes |
| `criterion_gap` (objection repeatedly sustained, no indicator captures it) | us, for decision | candidate new indicator for spec 8a (like Co-Scientist's meta-review, but we decide) |
| critique text | external hypothesis source (optional) | — |

- **Stop:** no new sustained objections, or round limit per hypothesis (2–3).
- **Budget estimate (working assumptions, check on the first run; prices to be taken from current data):** one prosecution–defence debate ≈ 3 rounds × 2 sides + 1–2 judge calls + 1 output call ≈ 8–10 calls; ≈ 3 check requests × 3–5 verifier calls ≈ 10–15 calls; ≈ 20–25 calls and ≈ 0.3–0.4 M input tokens per strong hypothesis per round (≈ 15k tokens per call). 20 strong hypotheses × 2 rounds ≈ 800–1000 calls, ≈ 12–15 M input tokens. Competitor pairs: 5–10 × ≈ 8 calls. New variants: one verifier run each; АСПИД recomputation is free. Rules + АСПИД filter the bulk almost for free; the LLM budget goes to the top (Co-Scientist spends it on a tournament over the whole pool). Equal-budget comparison: baselines get the same total call budget.
- **Packets and thresholds (from HyGRAIL `2609.02056`, 2026-10-19):** debate packets are rendered deterministically from the card and evidence records by templates, not summarized by an LLM (HyGRAIL: template naturalization beat LLM naturalization); evidence per claim is capped (more evidence did not reliably help and sometimes hurt; compact two-sided evidence beat more retrieval, and evidence from both endpoints of a link added 0.15–0.22 F1); the entry threshold to judges (P(top-k) ≥ 0.5) is a default to be calibrated on the backtest, like HyGRAIL's ambiguous region [a*, b*] set by purity on a validation split.
- **Risk:** plausible but empty objections. Guard: record references required; an objection becomes a check, not a score, so an empty one finds no evidence.

### 2.4 Closing the evolution loop (draft, 2026-10-19)

The loop reuses existing parts (refinement, verifier, АСПИД, debates); generation and "creative" operators remain out of scope for now.

```
pool → normalizer → admission → verifier → card → АСПИД → top
         ↑                         ↑                        ↓
         └── new variants ←────────┴── checks ←───────── debates
```

1. Debates on the top produce `check_request` and `refinement` outputs (section 2.3).
2. Checks update existing cards.
3. Refinements create new hypotheses (`origin: internal`, `parent_id`) that go through admission, the known-result check and the verifier like external ones.
4. АСПИД recomputes the ranking → new top → repeat.

**Difference from Co-Scientist evolution:** variants are directed by a specific sustained objection (not generic strategies such as "combine" or "think out of the box"), and fitness is АСПИД over verified facts, not an LLM-judged Elo. A variant cannot climb by rhetoric, only by becoming better supported, cheaper or more informative.

**Mutation operators in card terms** (partly rule-generated from the card structure; the LLM only phrases the text, which the normalizer parses back):
1. Concretization: narrow qualifiers (sex, age at start, dose) to address the objection.
2. Next rung: same intervention, next system per `next_step`.
3. Analog substitution: same target, e.g. better safety (via KG).
4. Combination: two `mechanism_neighbour` interventions in one hypothesis (the card already holds a list of interventions); the crossover analog.
5. Discriminating hypothesis: from a `competitor` pair, a mechanistic hypothesis that separates them.
6. Exclusion of an alternative route: add a control when a check could not rule the alternative out.

**Guards:**
- Known-result check (spec 4a) keeps variants from drifting into the published literature.
- Flood control: cap on variants per parent; dedup via `duplicate`/`variant` proximity; cap per family or mechanism cluster in the top (so the top is not 20 rapamycin variants).
- Refinement cost counts towards the system budget (spec 4a).
- Stop: top stable (rank correlation between iterations), no new sustained objections, or budget exhausted.
- Goodhart on indicators (e.g., drifting to cheap worm experiments) is partly offset by the trade-offs inside АСПИД (effect level vs cost); monitor on runs.

**Transition categories, rule-based (agreed 2026-10-19; categories from DiscoveryRSI `2610.23839`, there judged by an LLM):**

| Category | Rule (parent → variant) |
|---|---|
| repair | the variant removes a sustained objection: its check passes, or the alternative is now discriminated by the decisive experiment |
| progress | at least one indicator improves through verified facts or a cheaper decisive experiment, without an objection being repaired |
| repetition | the variant is a `duplicate`/`variant` (spec 8b) of an existing hypothesis with unchanged indicators |
| insufficient evidence | key claims of the variant are `unverified` or `unresolved` |

Uses: stop a family when repetitions dominate; share of repair + progress as a loop-quality metric; per-operator statistics (which mutation operators yield progress), usable to choose operators (e.g., a simple bandit), a light version of DiscoveryRSI's harness replay without retraining.

**Form over substance (agreed 2026-10-19).** DiscoveryRSI's self-improvement raised "form" dimensions while importance and novelty fell. Our fitness is facts, but the analogous risk is **narrowing to a subgroup where a result happens to be positive** (garden of forking paths). Guards: (1) the existing status rule (support only from a subgroup while the primary outcome is null → `contested`); (2) **conflict inheritance**: a variant created by narrowing carries the parent context's counterevidence visibly; (3) per-round monitoring of "substance" indicators (effect level, novelty) vs "form" indicators (context specificity, alternative coverage), with an alarm when the first fall while the second rise.

**Evaluation caveat:** the backtest measures selection, not evolution (new variants have no historical outcomes). Report two modes: (1) selection from a given pool, the main claim, tested by backtest; (2) full loop vs Co-Scientist's full loop. For (2), variants generated as of date T can be matched against literature after T (HindSight idea), valid only with an honest knowledge cutoff at T, so it depends on the contamination question (section 7, item A1).

**Retrospective evaluation protocol for the full loop (agreed 2026-10-19).** Run the loop "in the past" and check whether it anticipated what was later tested and what held up.
1. Snapshot at date T: KG G_T (observations published ≤ T) and the hypothesis pool P_T available at T.
2. Run the full loop on G_T only (retrieval and verifier restricted to ≤ T) → variants V.
3. Future window (T, T + Δ]: observations published after T.
4. Matching: for each variant, post-T observations matching its outcome claim by the card-similarity function (spec 8b), reported by level: exact (same intervention, species, endpoint, relation), variant (qualifiers differ), analog (shared target or class).
5. Outcome: apply the variant's decision criteria (spec 8c) to the matched observation → supports / weakens / inconclusive.

| Metric | Meaning |
|---|---|
| match rate | share of variants anticipated by later work; structured counterpart of DiscoveryRSI's "inspiration rate" (which uses a lexical gate and one LLM judge) |
| bet precision | among matched variants, supported vs weakened (absent in DiscoveryRSI) |
| lead time | time from T to the first matching publication |
| ranking quality | selection mode: the metrics of item A2 (AUC, rank correlation, precision@k, calibration) for the ranking at T vs outcomes after T |

Comparisons: parents only vs parents + variants (does evolution add anything); random variants from the same operators (do operators alone produce matches); Co-Scientist evolution on the same G_T at equal budget.

Traps: popularity (fashionable directions get studied anyway; control with random variants and normalization by pre-T attention, e.g. publications per intervention); publication bias (positive results published more, so bet precision is inflated; ITP, which publishes negatives, is the cleanest subset); KG coverage (no match ≠ wrong; report post-T extraction recall); dependence (variants of one family correlate; bootstrap by family); **contamination** (retrieval can be cut at T, model knowledge cannot; debates are the most contaminated component, symbolic operators and the graph part are nearly clean; options: debates with models whose cutoff ≤ T, plus a loop run without debates to measure their contribution to "guessing the future"). Choice of T and Δ: aging is slow (a mouse lifespan study takes about three years), so Δ of 3–5 years is needed, while frontier models have 2025–2026 cutoffs; compromise: recent T with short Δ and only fast evidence (worms, flies, cells, trial registrations as an attention signal), long windows only with older models. Decide together with backtest contamination (section 7, item A1).

### 2.5 Expert in the loop (agreed 2026-10-19)

Two principles:
1. **Expert time is the most expensive resource.** Ask only where the answer changes the result the most; never ask the expert to score hypotheses on criteria (same reason as for LLM judges, section 2.2).
2. **Expert opinion is not mixed with facts.** It is stored as a separate `expert` layer of the card with who and when ([card spec, section 7a. Expert layer (agreed 2026-10-19)](hypothesis-card-spec.md)); the verified layer changes only through sources.

Seven entry points:

| # | Point | What the expert gives | Where it goes | Cost |
|---|---|---|---|---|
| 1 | Preference profiles | ordinal importance order of indicators | direct АСПИД input (section 2.1) | once per profile, minutes |
| 2 | Own hypotheses | raw text | `RawHypothesis` with `origin: expert`, same pipeline as any other source | as the expert wishes |
| 3 | Contested pairs at the top | "A is better than B" for a pair with P(A > B) ≈ 0.5 | linear weight constraint added to the profile ([aggregation spec, section 6a. Expert pairwise choices as weight constraints](aggregation-spec.md)) | one question per pair |
| 4 | Evidence conflicts at the top | decision on a `contested` claim with rationale | expert layer; the claim status changes only if the expert supplies a source, which then goes through the verifier | per conflict |
| 5 | Debate outputs | review of the objection list: accept / reject / add an alternative to the prediction table (spec 8c) | accepted objections drive mutation operators (section 2.4); added alternatives enter the prediction table with `source: expert` | per debate |
| 6 | Variants | approve a variant or propose a refinement | approved variants proceed; a proposed refinement is a new `RawHypothesis` with `origin: expert` and `parent_id` | per variant |
| 7 | Final portfolio | which hypotheses to take into work | decision recorded in the expert layer; becomes a validation label | per run |

**Pairwise choices (point 3).** A choice "A ≥ B" is the linear constraint Σ_j w_j (q_Aj − q_Bj) ≥ 0 on the weights; it is added to the profile constraints and sampled by hit-and-run, so АСПИД stays the only aggregator. Questions go to the pairs where the answer cuts the admissible weight set the most (P(A > B) closest to 0.5 among the top). Contradictory answers make the admissible set empty: this is a signal that an indicator is missing (`criterion_gap`, as in section 2.3), not a reason to drop answers silently. This is the logic of preference disaggregation / robust ordinal regression (Greco, Mousseau, Słowiński 2008, EJOR 191: 416–436, doi:10.1016/j.ejor.2007.08.013; not read yet).

**Evaluation.** Two reporting modes: **autonomous** (no expert input except the profile) and **expert-in-the-loop**. Comparison with the baselines runs in autonomous mode, so the expert does not give our system an unfair advantage. Expert labels from points 3 and 7 are the top validation tier (the "bonus" in section 7, item B4), not the main ground truth. The number of expert questions per run is reported as cost.

## 3. Verification cannot be run "a little" → estimate cost and time instead

- In aging, a cheap pilot is not a small version of the decisive test (no 5-minute lifespan study). Cheap steps test **necessary conditions** (Popper-style falsifiable implications on public data), not the hypothesis itself.
- Reframe: for each hypothesis estimate **decisive-experiment cost, duration, and success probability** without running it; rank by expected value per cost under time/budget constraints (superseded 2026-10-19: cost and time are АСПИД indicators, see the end of section 7), and show which assumption the rank depends on.
- Cost/time estimation is closer to engineering because **ground truth exists** (registries, past studies). Related literature seen (abstracts only, not read): TrialDura `2404.13235`, CT Open `2604.16742`, CTP-LLM `2408.10995`, SPOT `2304.05352`, pTRS `2512.00586`, enrollment prediction with uncertainty `2507.23607`, TrialAtlas `2609.21859`.
- Method sketch (now the decisive experiment comes from the card, `decisive_experiment` and the evidence profile's `next_step`, spec 8a): LLM extracts a **minimal decisive experiment** (system, endpoint, intervention type) → match to a **reference class** of past trials/studies (ClinicalTrials.gov, ITP, DrugAge) → distribution (median + 80% interval), not a point number → backtest on historical studies (coverage, calibration).
- **What exists for duration/cost/outcome prediction (checked 2026-10-14, partly read):** duration: TrialDura `2404.13235`, drug trials from ClinicalTrials.gov (trials under 10 years), reported MAE 1.04 years and RMSE 1.39 years (read abstract and dataset setup; code link is anonymized, weights not confirmed). Outcome: CT Open `2604.16742` (read): dynamic, decontaminated benchmark of RCT outcome questions; classic ML such as Random Forest was competitive with LLMs, RAG helped modestly, agentic search was costly, and a model with a later knowledge cutoff scored better on the older window (contamination evidence). Enrollment with uncertainty `2507.23607` (abstract only). **Cost: no learned cost-prediction model found**; only Moore et al. 2018 modeled costs via a CRO tool. **Preclinical/aging experiments: nothing found.** So duration/outcome for human drug trials has baselines to compare with; cost and preclinical estimates must be built from registries, RePORTER and own tables.
- Caveats: human-trial reference classes are rich, mouse/exploratory ones are thin; cost depends on who pays and where, so give order of magnitude and class (months/years/decades); do not quote success-rate numbers from memory, take them from primary reviews.

**Current decision (2026-10-20): one simple indicator `path_to_human` with three classes.** The task needs a clear split into cheap, medium and expensive hypotheses, not a dollar figure built on a dozen assumptions. Classes = number of preliminary steps before a human trial with marker or function endpoints: 0 (human safety data and a supported mammalian effect exist) → cheap; 1 (one of the two is missing) → medium; 2 (both missing, e.g. a new compound with only worm or cell data) → expensive; gene target without a drug → unknown. One ordinal indicator replaces `cost` and `time` (they would count the same thing twice). The anchors and regulatory facts below stay as the justification for why the classes differ by orders of magnitude; dollar classes, durations by endpoint and a ClinicalTrials.gov duration table are developed only on demand.

**History of the decision (2026-10-19 → 2026-10-20): rank by the path to humans, show the next step separately.**
- **What is costed for ranking:** the path from the current evidence to the first experiment in humans (aging is the goal, a human lifespan trial is not feasible, so the end point is the first trial with marker or function endpoints). **Simplified model (decided 2026-10-20, baseline):** two questions and one trial. (1) Safety data in humans exist (approved drug, clinical-stage compound, diet)? If not → step "preclinical safety package". (2) A supported effect in mammals exists? If not → step "mouse study" (kept mandatory also for approved drugs: not a legal requirement, but ranking should not push human trials without mammalian efficacy data). (3) Human trial with marker or function endpoints, always. Four path types; replication counts and contested rungs stay in the next step, outside the ranking. Step durations come from reference classes by endpoint (mouse lifespan: years, ITP birth-to-publication 4–5 years; mouse healthspan: months; human marker trial: months, e.g. 3 months for the NR trial; human function trial: up to 2 years, e.g. 24 months for metformin–frailty). Toxicology duration and cost: no anchor yet (unknown, drawn uniformly). Expected spread: about 4–6 levels from months to 5+ years, enough for a baseline indicator; it estimates what has to be done, not the real calendar time (funding, recruitment and failure risk are not modelled).
- **Regulatory facts behind the model (checked 2026-10-20):** formal requirements concern safety, not efficacy. A new compound needs an IND with a nonclinical safety package per ICH M3(R2): repeat-dose toxicity in a rodent and a non-rodent species, safety pharmacology, genotoxicity; animal efficacy is not legally required. A lawfully marketed drug can be exempt from the IND (21 CFR 312.2(b)(1)) if the study does not support a new indication or labeling change, does not significantly increase risk by dose, route or population, and follows IRB review and informed consent; formally such a drug can go from worm data straight to a human trial with ethics approval only. Sources: [21 CFR 312.2](https://www.law.cornell.edu/cfr/text/21/312.2), [FDA M3(R2) Q&A](https://www.hhs.gov/guidance/sites/default/files/hhs-guidance-documents/FDA/M3%28R2%29Nonclinical-Safety-Studies-for-the-Conduct-of-Human-Clinical-Trials-and-Marketing-Authorization-for-Pharmaceuticals--Questions-and-Answers.pdf), [EMA FIH requirements](https://www.ema.europa.eu/en/documents/presentation/requirements-first-human-clinical-trials_en.pdf).
- Superseded on 2026-10-20 by the simplified model above: the chain of `next_step` rungs (replicate → next rung …) up to and including the first human study. Cost and time of this path are the АСПИД indicators (spec 8a). Reason: the practical question is "what to invest in", and the next step alone favours immature hypotheses (a worm study is cheap because evidence is thin).
- **The next step** (`next_step` with its own cost and time) is shown in the card and the report as practical information ("what to do next and what it costs"), outside the ranking.
- **Double counting:** `translational_distance` (ChEMBL max phase) is removed as a separate indicator (2026-10-20): its content is question (1) of the path. The path still correlates with `effect_level` (question 2); check on real cards (item D14) and, if needed, constrain weights in the profiles.
- **Cost from order-of-magnitude classes**, not point estimates: point costs are modelled, not observed, with intervals of several-fold. Each step gets its class midpoint; the path cost is the sum on a log scale with fixed bounds. Time is the sum of step durations (durations are observable: registries, lifespan of the strain).

**Cost anchors (checked 2026-10-19; NIH RePORTER API, PubMed, institutional rate sheets):**

| Class | Anchor | Order of magnitude |
|---|---|---|
| Multi-site mouse lifespan test (ITP) | ITP grants, total per fiscal year: U01AG022303 (U Michigan) + U01AG022308 (Jackson Lab) + U01AG022307 (UT Health San Antonio) + U24AG066346 (data coordinating centre) = $4.76M (FY2023), $5.22M (FY2024), $5.11M (FY2025); 6–11 compounds per annual cohort (C2017: 8 tests, PMID 36179270; 2021 cohort: 6, PMID 40973907; 2026 report: 11, PMID 41843349) | ≈ $0.45–0.85M per compound test (3 sites, both sexes, full lifespan; awards include indirect costs and also fund extra measurements, so an upper-side estimate; NIA-supplied animals and drug may add) |
| Multi-site worm test (CITP) | U01AG045829 (Oregon) + U01AG045844 (Buck) + U01AG045864 (Rutgers) = $1.92M (FY2023), $1.83M (FY2024), $1.73M (FY2025); ≈ 27 compound tests published 2023–2026 (Data_Sources 9.4) | ≈ $0.2–0.3M per compound test (strain/species panel, 3 sites); very rough, tests per year vary |
| Single-lab mouse cohort, housing only | per diem $0.82–1.40 per cage per day at US universities for internal users, $2.80 for external users (Toledo, Ohio, Indiana, Louisville, WPI rate sheets FY2025–26) | housing alone is small (≈ $10⁴ for ~20 cages over ~3 years); labour, diet with drug and pathology dominate, which is why the program anchor is preferred over a component model |
| Human trial, industry | pivotal trials for FDA approvals 2015–2016: median $19.0M (IQR $12.2–33.1M), PMID 30264133; 2015–2017: median $19M per trial, $41,413 per patient, PMID 32532786; phase 1 $1.4–6.6M, phase 2 $7.0–19.6M, phase 3 $11.5–52.9M by therapeutic area (2004–2012 data, not inflation-adjusted), PMID 26908540 | 10⁶–10⁷ (phase 2 marker trials) to 10⁷+ (clinical outcomes); academic marker trials are likely cheaper, no verified anchor yet |
| Human marker trial, academic (NIH-funded) | R01AG052697 metformin for preventing frailty, RCT n = 120, 24 months: $2.68M total awards FY2017–2022 (n from the ancillary R01AG069690 abstract); R01AG061514 nicotinamide riboside, phase IIa RCT n = 118 (59/group), 3 months, single site: $3.09M FY2019–2023; U01AG076941 everolimus 24 weeks, older insulin-resistant adults: $4.34M FY2022–2024 (n not in abstract) | ≈ $2.7–4.3M per trial, ≈ $22–26k per participant (awards include indirect costs and mechanistic assays); same order as industry phase 1–2 |
| Single-lab worm study (automated service) | University of Washington Nathan Shock Center, WormBot: "Estimated costs are $500 per plate"; "Each plate can accommodate 12 experiments of 20-30 animals per experiment" (page © 2020; final price on consultation) | ≈ $10²–10³ per compound (several doses and replicates), excluding design and analysis labour |
| Single-lab fly study | no verified anchor | lowest class with worms |

Ordinal cost classes (draft): single-lab invertebrate (≈ 10²–10⁴) < multi-site invertebrate (≈ 10⁵) < multi-site mouse lifespan (≈ 10⁵·⁷–10⁶) < human marker trial (≈ 10⁶·⁴–10⁷: academic $2.7–4.3M, industry phase 2 $7–20M) < human clinical-outcome trial (≥ 10⁷). Classes are combined by summing midpoints (maximum class as a sensitivity check): almost every path ends with a human trial, so the maximum would be nearly constant across hypotheses, while the sum shows whether mouse and toxicology steps are needed (changed 2026-10-20). Open: an anchor for fly studies and for single-lab mouse lifespan studies (component model only); academic marker trials and worm studies anchored 2026-10-19.

## 4. Success formalism (draft)

Success should be tied to a formalism, possibly starting from the **12 hallmarks of aging** (López-Otín 2023: genomic instability, telomere attrition, epigenetic alterations, loss of proteostasis, disabled macroautophagy, deregulated nutrient sensing, mitochondrial dysfunction, cellular senescence, stem cell exhaustion, altered intercellular communication, chronic inflammation, dysbiosis).

- Hallmarks = **coordinate system**, not a success predictor: shared ontology, coverage map (crowded vs empty hallmarks), mechanism-chain coherence check. They are overlapping and interdependent; a hypothesis touching many hallmarks is as often vague as strong (my opinion, not from a source). Cannot be a success formula without calibration on outcomes.
- **Superseded 2026-10-18:** the ladder below is replaced by the evidence profile (gate + three axes: effect level, robustness single/replicated, mechanism; flag multi_site_program; derived next step) in [card spec, section 8. Evidence profile (computed; replaces the S0–S5 ladder, agreed 2026-10-18)](hypothesis-card-spec.md). Reason: the ladder mixed proximity to humans with replication, and S0 mixed plausibility with non-contradiction. Kept for history.
- **Ordinal success ladder** instead of one probability:
  - S0 mechanism plausible, no contradiction in literature
  - S1 effect in cells / in vitro
  - S2 effect on lifespan or healthspan in a model organism
  - S3 independent replication (e.g., multi-lab programs)
  - S4 effect on surrogate markers in humans
  - S5 clinical benefit
- Per hypothesis: conditional chance per step, base rates from history by (intervention class × hallmark), shifted by hypothesis-specific evidence. DrugAge-style data is positively biased (publication bias): correct for it. Multiplying step probabilities assumes independence which fails: show intervals and rank by ladder level and confidence, not by raw product.
- Needs a backtest: interventions with known fate (got a positive multi-site program result, e.g. ITP, or not), predicted from data dated before the result.

## 5. Structured hypothesis card (draft schema)

> Superseded by sections 5a, 5c and [card spec](hypothesis-card-spec.md); kept for history.

Purpose: one format for the generator prompt and for the normalizer agent (external free-text hypotheses are parsed into the same card). Benefits: comparable fields for the judge (reduces style effect; judges are swayed by style per `2608.01666`, abstract only), direct inputs to cost/time, analog search and falsifiable sub-claims. Rule: every field may be `unknown`; every consensus or analog claim needs a source + quote, otherwise `unverified`.

```yaml
id: H-0001
claim: one sentence, what is proposed and what it should lead to
intervention:
  type: small_molecule | gene | diet | device | cell | other
  entity: name + identifier (ChEMBL, UniProt) if available
  regimen: dose/regimen or unknown
mechanism:
  target: molecular target
  pathway: GO / Reactome terms
hallmarks:
  - hallmark: cellular_senescence
    direction: decrease
    evidence: speculative | supported | established
outcome_claimed:
  endpoint: lifespan | healthspan | biomarker | disease | mechanism
  species: mouse | human | ...
  expected_effect: what is expected to be gained
analogs:
  - name: ...
    result: positive | null | negative
    species: ...
    replicated: yes | no | unknown
    source: link + quote
consensus:
  - subclaim: ...
    status: established | supported | contested | speculative | refuted
    sources: [link + quote]
counterevidence: [...]
decisive_experiment:
  system: cells | mouse | human
  endpoint: ...
  duration_class: weeks | months | years
falsifiable_implications: [...]
unknowns: [...]
```

## 5a. Pipeline objects: strict separation (agreed direction, 2026-10-15)

Only the declared layer comes from the hypothesis. Everything with evidence is a processing result. Each stage writes only its own object and never edits earlier ones.

| Object | Written by | Contents | Must not contain |
|---|---|---|---|
| Raw hypothesis | external generator | free text | — |
| Card, declared layer | normalizer, from the hypothesis text only | narrative (Heilmeier), PICO(TS), claim graph nodes + edges, no statuses | evidence, statuses, scores |
| Evidence store | source connectors, independent of hypotheses | normalized evidence records / KG observations | anything about a specific hypothesis |
| Verification results | verifier | per claim: matched evidence, status, refusals of necessary-condition checks | — |
| Assessment | deterministic code | rule-based indicators (spec 8a), evidence profile, cost/time, quality flags, declared-vs-verified divergence | model opinions |
| Judge packet | assembler (a view) | verified claims with statuses and quotes, assessment, fixed format, generator identity hidden | self-assessments presented as facts |
| Alternatives, prediction table, decision criteria | pipeline component after the verifier (spec 8c) | alternatives with status, predicted patterns, criteria | points for declared alternatives |
| Debate outputs | debates on strong hypotheses (section 2.3) | check_request, refinement, discriminating_experiment, criterion_gap | scores, verdicts |
| Expert layer | expert (spec 7a) | decisions with who/when, rationale, optional source | edits to other layers |

## 5b. Evidence record: what "every claim carries its sources" means

An evidence record lets anyone open the source and find the exact fragment. Real example (fetched 2026-10-14): claim "rapamycin extends lifespan in UM-HET3 mice started late in life".

```yaml
- source: PubMed
  record_id: PMID:19587680            # Harrison et al. 2009, Nature
  study_type: primary_experiment
  location: abstract, sentences 2-3
  quote: "Here we report that rapamycin, an inhibitor of the mTOR pathway, extends median and maximal lifespan of both male and female mice when fed beginning at 600 days of age. On the basis of age at 90% mortality, rapamycin led to an increase of 14% for females and 9% for males."
  quote_role: finding
  metric: age at 90% mortality
  supports_claim: yes
  qualifiers_match: {species: yes, age_at_start: yes, sex: yes}
  tier: peer_reviewed_primary
- source: DrugAge
  linked_pmid: 19587680
  fields: {dosage: "14 ppm food", age_at_initiation: "20 months", avg_lifespan_change_percent: 13, significance: S, ITP: Yes}
  metric: average lifespan
  tier: curated_database
```

Lessons from the same abstract: "rapamycin, an inhibitor of the mTOR pathway" is **background**, not a finding of this study; "Rapamycin may extend lifespan by postponing death from cancer, by retarding mechanisms of ageing, or both" is **speculation**. A plain PMID link would hide both distinctions. The two records report different metrics (+14% at 90% mortality vs +13% mean): without a `metric` field this looks like a contradiction. Pipeline checks: quote exists verbatim; quote entails claim; qualifiers match; role; quality flags. Empty evidence = `unverified`, not false.

## 5c. Hypothesis card v2 (decisions confirmed 2026-10-15 → [card spec](hypothesis-card-spec.md), examples [card examples](hypothesis-card-examples.md))

Principles: unestablished ≠ default (`unknown`), every claim cites, declared vs verified separated, necessary-condition checks refuse only, ordinal levels instead of pseudo-probabilities.

Layers: (1) identity and source; (2) narrative (Heilmeier + NIH Significance/Innovation/Approach), each field two-layered; (3) PICO(TS) core with `hypothesis_type` (interventional / mechanistic / biomarker / observational); (4) **claim graph**; (5) computed assessment.

```yaml
claims:
  - id: c1
    subject: {label: rapamycin, id: "CHEBI:9168"}
    relation: inhibits                 # closed vocabulary, shared with the knowledge-graph design
    object: {label: mTORC1}
    qualifiers: {species: human, dose: unknown, direction: decrease}
    role: premise                      # premise | mechanism | analog | outcome | translation
  - id: c2
    subject: {label: mTORC1 activity}
    relation: promotes
    object: {label: cellular senescence, hallmark: cellular_senescence}
    role: mechanism
  - id: c3
    subject: {label: rapamycin}
    relation: extends_lifespan_in
    object: {label: Mus musculus, strain: UM-HET3}
    role: analog
  - id: c4
    subject: {label: intermittent rapamycin}
    relation: improves_healthspan_in
    object: {label: human, population: older adults}
    role: outcome                      # root claim
edges:
  - {from: c1, to: c2, type: requires}
  - {from: c2, to: c4, type: supports_if_true}
  - {from: c3, to: c4, type: analog_of}
```

Benefits: weak links visible; novelty measured per edge; leaves = falsifiable implications; hallmarks attached to claims, not to the whole hypothesis; evidence profile computed from outcome/analog claims.

Decided 2026-10-15 ([card spec](hypothesis-card-spec.md) section 2): (1) atomicity rule (proposed: one relation, one context, checkable by one source type); (2) closed vocabulary (~15 relations + flagged `other`); (3) generator emits narrative + PICO only, a separate normalizer builds the claim graph; (4) separate mini-schema for biomarker hypotheses or `relation: predicts`; (5) storage: Pydantic vs JSON Schema (+ YAML for people). Format inspirations recorded: NIH review factors (Importance = Significance + Innovation; Rigor and Feasibility = Approach), PICO(T/S), Heilmeier's 8 questions (incl. risks, cost, time, mid-term and final exams).

## 5d. Own knowledge graph (direction agreed, 2026-10-15)

Proposal: build our own knowledge graphs (several, not necessarily one), starting with lifespan; it simplifies RAG, extends tools, fixes an ontology with defined relations that strictly formalizes the cards, and is a likely paper contribution. Assessment: not a utopia; plumbing is routine, the contribution is in contextual observations, role-aware extraction, contradictions, evaluation and temporal snapshots. Full design, landscape (HALD critique, AgingBank, AgeFactDB, SynergyAge, AGEID, Wikidata, ORKG, Monarch …) and MVP: the knowledge-graph design.

## 5e. Literature volume and its implications

PubMed 2025 (counted 2026-10-15, crude queries): 12,250 papers with MeSH Aging/Longevity; 2,347 reviews among them; 113 RCTs; 11 RCTs with healthspan/biological-age/clock endpoints; ≤489 rodent lifespan papers (upper bound); 6 mention ITP. DrugAge curates 2–7 rodent lifespan papers per year (2014–2021) and almost nothing after 2021 (lag). Implications: the decisive layer can be read in full; own extraction needed for recent years; most claim links will stay `unknown`; analogs mostly from invertebrates (DrugAge: 1,586 worm and 981 fly rows vs 372 mouse); the backtest will be small, so include mechanistic claims and model-organism outcomes (resolved in section 7, item A2: ITP/CITP pool, template hypotheses). Details: the knowledge-graph design (section 6. Literature volume (sizing)).

## 6. Mechanics borrowed from related work

- Pairwise comparison of unexecuted candidates beats absolute scoring (RPM `2608.13940`); LLM-only pairwise accuracy was only ~68–69% in their offline test, so pure LLM judging is not enough. (Not adopted in the main system: rule-based indicators + АСПИД; pairwise LLM comparison only in baselines and the ablation.)
- Hidden evaluation split + externally computed metric (AIRA² `2603.26499`).
- Falsifiable sub-hypotheses with e-values and Type-I control (Popper `2502.09858`), already demonstrated on biological public data (GTEx, GWAS, BioGRID).
- Rubric discovery against historical outcomes (APRES `2603.03142`) as a template for learning promise criteria from backtests.
- Novelty is a retrieval problem (Glitters `2502.16487`): finding the source is the bottleneck, not comparing.
- Judges can be gamed by editing justifications (NeurIPS checklist study `2411.03417`): evaluate against sources/data, not the justification text.
- Diversity matters: portfolio selection, not top-1 (Ideation Diversity `2511.15593`).

## 6a. Where hypotheses come from and how they fail (2026-10-18)

Facts checked via PubMed API on 2026-10-18.

**Sources and their typical failure:**

| Source | Example | Typical failure |
|---|---|---|
| Genetic screens in model organisms | *daf-2* mutants live >2× longer, requires *daf-16* (PMID 8247153) | huge effects in worms/flies that shrink or vanish in mammals; genetic background confounds (Sir2 overexpression: longevity disappeared after outcrossing and proper transgenic controls, PMID 21938067) |
| Human genetics / long-lived people | *FOXO3A* genotype associated with longevity, OR 2.75 (PMID 18765803); FOXO3 is the human ortholog of *daf-16* | association, not cause; population-specific; small effects |
| Drug repurposing from epidemiology | metformin users outlived matched non-diabetics (PMID 25041462) | confounding and biases of observational data; a Danish registry study incl. discordant twins found higher mortality instead (PMID 36287641) |
| Reasoning from mechanism / hallmarks | senescent cells → senolytics D+Q, +36% post-treatment survival in old mice (PMID 29988130; authors hold patents) | each link in the chain can fail; resveratrol's SIRT1 activation was an assay artifact of a fluorophore (PMID 15684413) |
| Comparative biology | naked mole-rat high-molecular-mass hyaluronan (PMID 23783513) → *nmrHas2* mice: extended lifespan, improved healthspan (PMID 37612507) | trait may not transfer to another species |
| Mimetics of known interventions | resveratrol mimics transcriptional signature of dietary restriction but did not extend lifespan of ad libitum-fed mice (PMID 18599363); null in ITP (PMID 20974732) | "looks like X" on markers ≠ does what X does |
| Computational (signatures, clocks, LLMs) | — | cheap and many, high false-positive rate; clocks are surrogate endpoints |

**Recurring failure modes** (what makes a hypothesis "bad" beyond vagueness):
1. Premise refuted: antioxidant supplements, from the oxidative-damage theory; in 47 low-bias RCTs they increased mortality (RR 1.05, PMID 17327526).
2. Mechanism artifact (resveratrol/SIRT1 above).
3. Effect via an indirect route: metformin extends worm lifespan by altering *E. coli* metabolism and can increase or decrease it depending on the bacterial strain (PMID 23540700); lowering core body temperature by 0.3–0.5 °C alone extended median lifespan 12–20% (PMID 17082459), so any intervention that lowers food intake or temperature can look anti-aging.
4. Uncontrolled genetic background / wrong controls (Sir2 above; short-lived controls).
5. Observational correlation read as causation (metformin above).
6. Healthspan or marker improvement read as lifespan extension (resveratrol above).
7. Already known (→ `known_result`) or already refuted (→ gate).

**What a good hypothesis has:** a definable decisive experiment; explicit context; independent lines converging (worm genetics + human genetics + pharmacology, e.g. *daf-16*/FOXO3); a mechanism whose links each have evidence; alternative routes excluded by controls; an endpoint that matches the claim; a realistic path to humans (druggable target, achievable dose).

**Coverage by the current card ([card spec](hypothesis-card-spec.md)):** modes 1, 2, 7 are covered (gate, `mechanism` axis, `known_result`); 4 partly (flag `short_lived_controls`); 5 and 6 were not explicit (now: 5 via P2, 6 via the endpoint rule from P1; 3–4 partly via the alternatives of spec 8c). **Proposals (discussed 2026-10-18):**
- P1 (**accepted in reduced form**: a field would not make the verifier more accurate, since a verifier that wrongly sets `supported` would set the field wrongly too. Instead: an endpoint rule in spec section 7 + fixture Example 5 in [card examples](hypothesis-card-examples.md)). Originally proposed: add `endpoint` to `qualifiers_match` (lifespan | healthspan | marker | disease), so a healthspan finding cannot support a lifespan claim (mode 6).
- P2 (**accepted**, added to spec section 8). Mark study design at the human rungs, like `marker_validation`: "human_clinical (observational only)" vs RCT (mode 5).
- P3 (**deferred**: overkill for the current stage). New flags `background_not_controlled` and `indirect_route_possible` (food intake, body weight, temperature, microbes) (modes 3–4). Alternative: record each as an explicit alternative-explanation claim.
- P4 (**deferred**: value unclear; revisit if the АСПИД ranking systematically underrates convergent hypotheses on the backtest). Count independent lines of evidence (different source types above) as a profile field; `robustness` counts labs for one claim, not convergence across lines.

## 6b. Prior-work check for the overall approach (first pass, 2026-10-19)

Scope: two alphaXiv searches (arXiv only), three web searches; abstracts read via the arXiv API, no full texts. Not covered in the first pass: PubMed and АСПИД sources (covered in the second pass below). Many relevant papers are from Aug–Oct 2026, so the picture moves fast; repeat before writing a paper.

**Verdict.** No work found that combines the chain we designed: verified structured card with a closed vocabulary shared with a KG → rule-based indicators (incl. typed proximity and novelty) → aggregation with random weights under an ordinal importance order (АСПИД/МРСП, international counterpart SMAA) → LLM debates only on the top, emitting checks and objection-directed variants. Individual components have close relatives; the novelty claim should be about the combination and about replacing LLM judgment with verified facts, not about stochastic multicriteria aggregation itself.

**Closest works by component:**

| Component | Closest work | Overlap | Difference |
|---|---|---|---|
| Admission by a decision rule | Lit2Test `2608.22948` | proposals precommit a falsifying outcome (six-field contract), so quality is "decidable rather than arguable" | ranking still by blind pairwise LLM judging (both orders) |
| Cheap filter, LLM only on hard cases, KG evidence | HyGRAIL `2609.02056` | GNN triage routes only graph-uncertain candidates to an LLM reviewer with KG paths; −54% LLM calls; compact two-sided evidence beats more retrieval | hypotheses are missing KG links (binary verification), the LLM is the final judge, no multicriteria aggregation |
| Hypothesis definition | DiscoveryRSI `2610.23839` | "evidence-grounded claims about consequential uncertainties, feasible investigations, explicit decision criteria, alternative explanations" (close to our card); reports correspondence with post-cutoff research (6.3%) | quality scored by automated/LLM assessment; generation-focused |
| Auditable evolution | HEP `2607.09195`; HypoEvolve `2609.15938` | explicit hypothesis–test–evidence–belief operations; GA over a hypothesis population with external measures (DepMap, Open Targets) | fitness/selection by LLM judgments; no verified card |
| KG-guided reasoning | HypoKG `2609.12260` | full KG paths make LLM hypotheses more mechanistically grounded ("evidence-disciplined") | generation study; rubric scored 1–5 |
| Experiment-guided ranking | MOOSE-Chem3 `2505.17873` | decomposes hypotheses into functional elements, clusters by mechanistic role | simulated experimental feedback, chemistry |
| MCDA with LLMs | AHP + LLM `2609.16779` | LLM runs the full AHP workflow; better agreement with experts (legal, university rankings) | the LLM produces the pairwise judgments; not hypotheses |
| Rubric ranking in drug discovery | PharmaSwarm `2504.17967` | Evaluator LLM ranks by plausibility, novelty, in silico efficacy, safety | LLM rubric, no formal MCDA |
| Stochastic weights | SMAA (Lahdelma, Tervonen); drug benefit–risk (Tervonen et al., Stat Med 2011); IMI PROTECT rates SMAA as recommended for further appraisal | rank-order weights, Monte Carlo over weights and measurements | no LLM hypothesis ranking found with SMAA/TOPSIS (web search) |

**Evidence supporting our design choices:**
- LLM novelty/idea judges are unreliable: style bias (`2608.01666`); prompt framing flips the verdict on more than half of identical pairs (`2610.02022`); LLM judges rate model-generated research questions as highly novel while experts prefer the author-anchored ones (`2606.12071`). → novelty via KG, scores via rules.
- Judge consensus overstates evidence: average error correlation 0.21, ten judges ≈ 3.5 independent ones, stronger among frontier models across providers (`2609.22512`). → no reliance on panels of LLM judges for scores.
- Debate is not automatically better: a homogeneous three-agent panel ranged from +8.5 to −4.4 pp vs one agent on six groundedness benchmarks (`2608.00243`). → debates emit checks against records, not scores; use mixed model families; measure the debate effect, do not assume it.
- Evidence grading: the GRADE Working Group is building an official automated tool (GRADErater) under human oversight; Guyatt (2026) says LLMs cannot yet replace GRADE deliberation; LLM risk-of-bias (RoB 2) reliability drops in complex cases (JMIR 2026). → grades computed by rules from verified fields; the LLM extracts.

**Detailed reads (2026-10-19):** HyGRAIL from the alphaXiv report, DiscoveryRSI full text (all appendices).
- **DiscoveryRSI admits that fixed weights are arbitrary.** DFM-Bench aggregates eight hypothesis dimensions with weights 20/20/15/10/10/10/10/5, called "frozen internal protocol conventions, not empirically established optimal weights"; path and run rubrics use further fixed weight sets; the three AI reviewers are one model family with different prompts, which the authors call "correlated AI perspectives, not three independent expert opinions". This is the strongest positioning argument for АСПИД: a leading system acknowledges exactly the problem that ordinal importance with random weights addresses. Shared principle: unknown ≠ zero.
- DiscoveryRSI's hypothesis object H = (claim, investigation plan, decision criteria, alternatives) and its revision categories were adopted since: alternatives and decision criteria in spec 8c, revision categories as transition categories in section 2.4.
- After two self-improvement rounds DiscoveryRSI improved mostly "form" dimensions (falsifiability 4.00→6.20, alternatives 4.44→5.98, data resolvability 3.73→4.99) while importance (6.48→6.04) and novelty (4.87→4.58) fell; human "advance over known work" was 2.31 for both their model and GPT-6 Luna. Warning for any loop optimized on a rubric.
- DiscoveryRSI's "inspiration rate" (6.3% vs 2.3–5.4%) is fragile: a lexical gate (≥ 3 shared non-stopword terms), one LLM judge (145 judgments propagated to 903 versions), strong format sensitivity (Claude retrieval 15 → 95 when titles were used as queries). A structured version via card-based similarity against post-T KG edges (spec 8b) is a better instrument for us.
- HyGRAIL is a selective-prediction cascade (reject option / model cascades) for KG link prediction: GNN scores, a validation-calibrated ambiguous region goes to an LLM with templated two-sided KG evidence. Low conceptual novelty; practical lessons taken into section 2.3.

**Second pass (2026-10-19):** full texts of Lit2Test and HyGRAIL (DiscoveryRSI already read in full); PubMed searches; АСПИД sources (see section 2.1).
- **PubMed:** no work combining MCDA/SMAA with LLM hypothesis ranking ("MCDA" + "large language model": 2 unrelated hits; MCDA + target prioritization / drug repurposing: 2 unrelated). SMAA: 21 records, 11 on drug benefit–risk (e.g., incretins in type 2 diabetes, 2023). The gap found in arXiv holds in PubMed.
- **Lit2Test (full):** a six-field contract (literature_gap, hypothesis, minimal_test, decisive_metric, supporting_result, falsifying_result) adapted from Registered Reports; blind pairwise judge in both orders; **order-sensitive cases (250 of 1,200) are isolated and reported, not averaged**; Bradley–Terry on order-stable cases only; bootstrap by context cluster; second judge from a disjoint family agrees on 86.1%. Findings relevant to us: falsifiability acts as an **admissibility floor** (it rarely separates natural proposals, while minimal test and decisive metric do), which matches our admission gate; a falsifier field is an auditability constraint, not a quality gain (on/off ablation); schema vs prose rendering of identical content does not move the judge; humans agree with the judge on 87.2% of decisive stable cases but inter-annotator α is only 0.238. The authors deliberately keep a holistic verdict, arguing that per-dimension scores would need cardinal, equal-weight treatment; this is exactly the problem АСПИД addresses with ordinal importance and random weights. Their critique of "future paper as answer key" (rewards one realized trajectory, invites contamination) applies to our retrospective evaluation; our protocol mitigates it by matching at several levels and scoring outcomes by decision criteria, but the single-trajectory bias remains a stated limitation.
- **HyGRAIL (full):** the headline F1 0.429 depends on one backbone/LLM pair (R-GCN + Qwen3-4B); with HGT the gain over the GNN is small (F1 0.117 vs 0.093), and one configuration with LLM naturalization falls to 0.092; one seed, a 3,000-node MatKG subgraph, closed-world negatives (an unobserved link is not a false hypothesis, as the authors note). The time split uses the oldest paper per edge. Its lessons (templates over LLM summaries, compact two-sided evidence, calibrated routing) are suggestive, not established; treat them as defaults to test.
- **ResearchStudio-Idea / IdeaSpark** (`2607.04439`, cited by Lit2Test) requires a falsification prediction with a negative control at generation time; not read.

**Bio Arena (https://bioarena.ru/, checked 2026-10-19 via its public API: dossiers, judge prompts, call logs, ranking).** An open tournament of longevity hypotheses; the closest running system to our task.
- Pipeline: anyone (including AI agents via MCP/API) submits a text; after acceptance the text is frozen. Moderation → semantic duplicate check → dossier → pairwise matches → Bradley–Terry rating (center 1000, scale 400, ridge regularization, 95% intervals, adaptive seeding).
- Dossier (gpt-6.1-sol, Europe PMC search, up to 30 sources with full text): author claims, observations with verbatim quotes (species, design, outcome type lifespan / function / marker, direction, significance, supports / contradicts), AI analysis of mechanism and benefit, uncertainties, an AI-proposed experiment kept separate from the author's. No numeric scores in the dossier. This is close to our verified layer.
- Match: the same model answers "which hypothesis should be investigated first", weighing mechanism plausibility, evidence for and against, potential human healthy-lifespan benefit and the nearest convincing experiment, by a detailed rubric in the prompt (scope vs justified benefit, learning from negative results, burden). Evaluated in both orders unless the first verdict has confidence ≥ 0.8; split decisions are resolved by higher confidence, then a coin.
- Scale on 2026-10-19: ~1,000 submissions, 343 hypotheses in the tournament, 6,818 matches; 304 of 343 from one AI agent ("Кайрос"); position swap changed the verdict in 8.6% of pairs; ~17k tokens per judge call, so the tournament costs on the order of 200M tokens (our estimate).
- Observation, not a conclusion: the judge is an OpenAI model, and hypotheses generated by OpenAI models have higher mean ratings (gpt-6-astra 1340, ChatGPT 1406) than those from other families (opus-5 588, fable-5.1 416, grok-4.7 663). Consistent with judge self-preference, but submitters and prompts differ, so the cause is not established here. Self-preference itself is documented: LLM evaluators score their own outputs higher than others' while humans rate them equal, and the bias correlates with self-recognition (Panickssery, Bowman, Feng, NeurIPS 2024, arXiv `2404.13076`); a quantitative metric and evidence that judges favour low-perplexity, familiar text (Wataoka, Takahashi, Ri 2024, arXiv `2410.21819`). Abstracts read.

| | Bio Arena | Ours |
|---|---|---|
| Who sets the ranking | LLM judge, holistic pairwise verdict | rules over the verified card → АСПИД; no LLM score |
| Priorities | one implicit weighting in the judge prompt | explicit preference profiles; robustness across profiles |
| Evidence structure | quoted observations, combined by the judge | atomic claims, statuses, evidence profile (effect level by species, independent labs, multi-site programs), endpoint-match rule |
| Novelty | duplicate check only | KG of supported edges + typed proximity |
| Cost/time of the next experiment | "burden" in the judge's reasoning | reference-class estimate as an indicator |
| Alternatives | named in the judge rubric | generated, prediction table, decision criteria |
| Improvement | none (text frozen) | debates on the top → checks and refinements; evolution loop |
| Validation | position-bias statistics | retrospective evaluation on ITP/CITP outcomes, contamination-aware |
| Pool dependence | BT rating depends on opponents | values on fixed scales are pool-independent |
| Stage | running | design and specs |

Where Bio Arena is ahead: it runs on a real stream; full transparency (prompts, calls, tokens public); mature engineering (moderation, dedup, quotas); quoted dossiers already implemented. **Use:** a ready Co-Scientist-type baseline with an open pool: run our pipeline on the same ~340 hypotheses and compare rankings (where they disagree and why); its dossiers can serve as input to our card. **Plan (2026-10-19):** parse the Bio Arena pool for a test run once the implementation is done (shadow mode: our ranking per profile vs their BT rating, case studies of large disagreements). Integration into the site itself (second rating track, extra dossier fields such as lab/cohort, identifiers, dates; evolved variants submitted back via their API with a parent link) would need write access to Bio Arena.

**Argument for per-claim verification: the small key discrepancy (2026-10-19).** A model generates a plausible hypothesis, the same model rates it highly, experts overlook one small but decisive mismatch, and the experiment fails. Holistic judgment (model or expert) responds to overall plausibility, which is insensitive to such details; the card splits the hypothesis into atomic claims with their context (species, strain, sex, dose and regimen, age at start, comparator, endpoint) and checks every supporting record field by field; a mismatch means the record does not count and is visible as a refusal. Real cases where one detail decided the outcome:
- sex: 16α-hydroxyestriol extended male lifespan by 15% and shortened female lifespan by 7% in ITP (PMID 38753230); canagliflozin works in males only (PMID 32990681);
- dose and start age: astaxanthin and meclizine extended male lifespan in ITP (PMID 38041783) but showed no benefit at other doses or later start (PMID 41843349);
- endpoint: resveratrol improved healthspan of old mice without extending lifespan (PMID 18599363; fixture Example 5);
- population: human senolytic data come from IPF patients, not healthy older adults (PMID 30616998; Example 2);
- indirect route: metformin's effect in worms runs through their bacteria and depends on the bacterial strain (PMID 23540700).
Honest limit: only discrepancies in fields the card has and that sources document are caught; a detail in an unmodelled dimension (diet composition, housing temperature) or nowhere documented is missed too. The difference is that the error is localizable (which field was not matched) and the field list can grow as such cases are found; "the model found it plausible" cannot be localized at all.

**Positioning implications:** cite SMAA alongside МРСП; frame the contribution as "verified facts + rule-based indicators + stochastic aggregation instead of LLM judgment, with LLM effort concentrated on checks for the top"; related work: Lit2Test, HyGRAIL, DiscoveryRSI, HEP, HypoEvolve, AHP+LLM. DiscoveryRSI's post-cutoff correspondence metric is adopted in structured form as match rate (section 2.4).

## 7. Open questions / next steps (restructured 2026-10-19)

Status: the conceptual design of the pipeline is closed (card → admission → verification → alternatives and decision criteria → rule-based indicators → АСПИД per preference profile → debates only on the top → evolution loop → expert in the loop → retrospective evaluation). What remains is grouped by the kind of work it needs. Item numbers in older notes refer to the previous list; the mapping is given in brackets.

**A. Conceptual decisions (A2 and A3 decided; in A1 only the choice of T and model remains)**
1. **Backtest contamination (key risk)** [old 7]. Models already know later outcomes (e.g., that resveratrol failed in ITP), so a time split on data does not hide them. The choice of T and Δ for the retrospective evaluation of the full loop (section 2.4) depends on this decision.
   - **Our approach is structurally less exposed (agreed 2026-10-19, to be stated in the paper).** An LLM changes the ranking only through dated facts: the normalizer parses text (no outside facts), the verifier sets a status only with a verbatim quote from a source dated ≤ T, indicators and АСПИД are rules over those facts, and debate outputs are check requests that go through retrieval restricted to ≤ T (an argument "this failed in ITP" retrieves nothing before T and cannot move the ranking). Residual exposure: the verifier's reading of ambiguous evidence (low–medium) and variant generation in the evolution loop (high). In Co-Scientist the LLM judge sets the ranking directly, so contamination inflates the baseline more than our system: a win for us is a conservative result, a loss is inconclusive.
   - **Decided:** models are chosen by knowledge cutoff ≤ T (cutoffs are listed in the Comet API model catalogue); automatic date audit (no record after T reaches any component). Dropped: asking the model whether it knows the outcome (a model's self-report is not reliable evidence of not knowing).
   - **Outcome counts after candidate T** (done 2026-10-19): [data sources, section 9.4 Temporal discipline (for backtests)](data-sources.md). Top-quality clean outcomes (ITP + CITP) are ≈58 compound tests after end-2022 and ≈37 after mid-2025; the model choice is open. Masking compound names: rejected (too specific, adds complexity).
2. **Ground truth and label format for the backtest** [old 3]. **Decided 2026-10-19:**
   - **Pool = compounds selected for testing by ITP and CITP.** Each was a hypothesis before the test (nominated with a rationale, selected by the program) and has a published outcome under one protocol, negatives included. The pool is hard: every item already passed expert selection, so discrimination inside it shows value beyond that selection. Hypotheses without outcomes (e.g. the Bio Arena pool) serve only for ranking comparison, not for quality.
   - **Hypothesis format:** a template sentence ("compound X at dose D from age A extends lifespan of UM-HET3 mice"; worms analogously), so style plays no role; card evidence restricted to sources dated ≤ T.
   - **Label** by the decision criteria (spec 8c): supports (significant median lifespan increase in at least one sex) / does not support (no effect) / harmful (significant decrease); effect size (% median) and sex stored separately. A repeat at another dose or start age is a separate hypothesis (meclizine 2023 vs 2026).
   - **Metrics** for 40–60 outcomes: AUC positive vs rest (= share of correctly ordered pairs, so pairs and ranks do not conflict), rank correlation with effect size, precision at top k, calibration of АСПИД pairwise probabilities P(A > B).
   - **Two test sets.** (a) *Clean*: outcomes after the model cutoff (ITP + CITP, ≈ 40–60 tests, [data sources, section 9.4 Temporal discipline (for backtests)](data-sources.md)) for the comparison with baselines (Co-Scientist, a Bio Arena-style judge). (b) *Historical*: all ITP outcomes since 2008 and CITP since 2017 with a per-compound T (ITP ≈ 54 compounds in DrugAge up to 2024 + 17 tests in 2025–2026; CITP several dozen), for our system only, to test which indicators and evidence-profile axes carry signal (item D15). Allowed because our ranking takes model knowledge in only through the verifier's reading (item A1); residual leakage is estimated by comparing performance on (a) and (b).
   - **Human trials** (function and markers): an auxiliary label for `human_markers`-level claims only, outside the main metrics.
**B. Open decisions**
5. Content of the preference profiles: the concrete ordinal importance orders (the mechanism is decided, section 2.1; [aggregation spec](aggregation-spec.md)).

**C. Content work (conceptually decided)**
6. **Done 2026-10-20:** checklist of 14 alternatives with inclusion rules over card fields and discriminating designs (spec 8c); new card field `route`, new optional evidence fields `strain`, `dose`, `age_at_start`.
7. ~~Reference-class tables for cost and time~~ Replaced 2026-10-20 by the three-level `path_to_human` (section 3); finer tables only on demand.
8. Normalizer prompt (contract in spec section 9).
9. **Done 2026-10-20: both Co-Scientist versions are reimplemented as far as the papers allow.** Was: reimplementation scope for both baselines [old 6]: 2025 (Reflection types + Elo tournament + single-call simulated debates, section 2.3) and 2026 (TrueSkill + UCB, plagiarism penalty, claim-vs-log checks).
10. Card schema details together with the KG relation vocabulary [old 2]: extra fields for `observational` hypotheses — closed 2026-10-20, not needed; identifier policy for complexes — proposed (spec 12), belongs to the KG work (the knowledge-graph design).
11. Optional fifth worked example (SRSF1, PMID 42875585; fly ortholog knockdown PMID 41514095): quotes from PubMed, facts via API.

**D. Calibration and testing (needs runs)**
12. Entry threshold to judges (P(top-k), default 0.5), evidence cap per claim in debate packets, number of debate rounds.
13. Effect-size threshold in decision criteria (spec 12).
14. Correlated indicators (double counting in additive aggregation), sensitivity to the ordinal mapping (SMAA-O vs equal steps), Monte Carlo size ([aggregation spec](aggregation-spec.md) 5, 8).
15. Whether each evidence-profile axis carries signal on the backtest (spec 8, validation); drop axes that do not.

**E. Literature**
16. Before writing a paper [old 8]: re-run the prior-work search (first and second pass done, section 6b); Hovanov's 1996 monograph is not accessible online (library copy needed); SMAA implementation paper read in full ([aggregation spec](aggregation-spec.md)).
17. Unread items from the reading list [old 5]: PostTrainBench, DiscoveryBench family, ScienceAgentBench, ResearchBench, CORE-bench; CT Open / TrialDura if cost/time becomes central.

Superseded: [old 4] "final ranking formula (expected value per cost with time constraint, with intervals)" is replaced by АСПИД with preference profiles and `path_to_human` as an indicator (sections 2.1–2.2 and 3, spec 8a).

## 8. Reliability notes

- Fully read (alphaXiv reports): Co-Scientist, Gemini-based Co-Scientist extension, logit energy scoring `2608.17270`, HindSight, Scientific Taste, RPM, Popper, AIRA², AIRS-Bench, Ideation Diversity, APRES, HyperAgents, MLGym, NanoGPT speedrun, CURIE, AI Scientist, Scaling Laws position paper, NeurIPS checklist study, Si et al., Glitters. Full texts (section 6b): DiscoveryRSI, Lit2Test, HyGRAIL; SMAA implementation paper (Tervonen, Lahdelma 2007); Bio Arena via its API.
- Abstract/snippet only: most items of the literature map marked [A], clinical-trial prediction papers above, ASI-Arch.
- Some sources were read only as web previews: verify quotes before citing.

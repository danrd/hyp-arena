# Aggregation: implementation notes (АСПИД/МРСП and SMAA)

> Turns the indicators of [card spec, section 8a. Scoring indicators for АСПИД (draft, 2026-10-19)](hypothesis-card-spec.md) into a ranking with uncertainty, under an ordinal importance order (a named preference profile). Design decisions: [design notes, section 2.1 Aggregation without explicit weights: АСПИД / МРСП (proposed, 2026-10-15)](working-notes.md), [design notes, section 2.2 Judge role and its link to АСПИД (agreed 2026-10-18)](working-notes.md). Written 2026-10-19.

---

## 1. Sources and how far to trust them

| Source | Read | Used for |
|---|---|---|
| Tervonen, Lahdelma, "Implementing stochastic multicriteria acceptability analysis", *EJOR* 178 (2007) 500–513, doi:10.1016/j.ejor.2005.12.037 | **full text** (open copy, University of Coimbra repository) | algorithms, outputs, accuracy formulas (sections 3–6 below) |
| Lahdelma, Salminen, "SMAA-2", *Operations Research* 49(3) (2001) 444–454 | via the paper above | definitions of rank acceptability, central weights, confidence factors |
| Lahdelma, Miettinen, Salminen, "Ordinal criteria in SMAA", *EJOR* 147 (2003) 117–127 (SMAA-O) | via the paper above | random monotone mapping of ordinal levels |
| Tervonen, van Valkenhoef, Baştürk, Postmus, "Hit-And-Run enables efficient weight generation for simulation-based MCDA", *EJOR* (2013), doi:10.1016/j.ejor.2012.08.026; notes in *EJOR* (2014), doi:10.1016/j.ejor.2014.06.036 | titles only (Crossref) | sampling weights under arbitrary linear constraints |
| R packages `smaa` and `hitandrun` (van Valkenhoef, Tervonen) | documentation | reference implementation, function set |
| Hovanov N. V., «Анализ и синтез показателей при информационном дефиците», СПбГУ, 1996 | **not accessible** online | — |
| Hovanov, Kolari, Sokolov, *Math. Soc. Sci.* 2008; Hovanov, Yudaeva, Hovanov, *EJOR* 2009 | abstracts / bibliographic data | confirms the method family (AIRM) |
| Worked example of hierarchical МРСП with R code ([nbpublish 32328](https://nbpublish.com/library_read_article.php?id=32328)); application with fixed national/regional bounds ([sciup](https://sciup.org/opredelenie-integralnogo-pokazatelja-sostojanija-prirodnogo-obekta-kak-slozhnoj-14042496)); Wikipedia "Aggregated indices randomization method" | secondary | discrete weight grid, dominance probability, normalization practice |

**Equivalence.** For our use, МРСП (Hovanov) and SMAA-2 (Lahdelma, Salminen) are the same model: additive value function, weights uniformly distributed over the set allowed by the preference information, Monte Carlo over weights (and over uncertain indicator values). Differences are in emphasis: Hovanov works with a discrete weight grid (step 1/k) and reports expected index, its spread and dominance probabilities; SMAA adds rank acceptability indices, central weight vectors and confidence factors, and treats uncertain indicator values as distributions. Implement the SMAA machinery; report Hovanov's outputs as well (they are a subset). In the paper: cite both (Hovanov for АСПИД/МРСП, Lahdelma/Tervonen for SMAA).

## 2. Model

**Indicators.** Each hypothesis i has indicator values q_ij ∈ [0, 1], j = 1…n (spec 8a), oriented so that higher is better (invert "lower is better" indicators such as path_to_human).
- **Cardinal indicators** (effect size, late start; saturating counts: breadth, path plausibility, informativeness): normalize on **fixed reference scales**, not min–max over the current pool. Min–max over the pool (as in some МРСП examples) makes every hypothesis's value depend on which other hypotheses are present; when the evolution loop adds a hypothesis, the order of others can flip. Practice in applications of Hovanov's method already uses fixed bounds (e.g., national or regional minima and maxima), clipping values outside the bounds.
- **Ordinal indicators** (effect_level, robustness, mechanism, novelty levels, both_sexes, path_to_human): either a fixed mapping (equal steps) or **SMAA-O random monotone mapping**, which removes the equal-step choice: for an ordinal indicator with m_j levels, in each Monte Carlo iteration draw m_j − 2 uniform numbers in (0, 1), sort descending, prepend 1 and append 0; level ℓ gets the ℓ-th number (Tervonen, Lahdelma 2007, Algorithm 1). Recommended default: SMAA-O mapping; report sensitivity against equal steps.
- **Unknown values** (spec rule "unknown stays unknown"): in each iteration draw the value uniformly over its admissible range (for ordinal indicators: uniformly over its levels). This is SMAA's stochastic criteria measurement; data uncertainty and weight uncertainty then add up in the output spread. If the card gives an interval instead of a value (e.g. `late_start` from a verbal age, spec 8a), draw uniformly within that interval.

**Value function.** Additive: u(q_i, w) = Σ_j w_j q_ij. Both МРСП and SMAA-2 use this as the default. It is compensatory (a high value on one indicator can offset a low one); non-compensatory vetoes are handled before aggregation by the gate (spec section 8), not by the value function.

**Weights.** Feasible weight space W = {w ∈ ℝⁿ : w_j ≥ 0, Σ w_j = 1} (the (n−1)-simplex). Preference information restricts W by linear constraints:
- complete ranking: w_a ≥ w_b ≥ … (equality for equally important indicators);
- partial order: only some pairs ranked;
- intervals: w_min_j ≤ w_j ≤ w_max_j;
- lower bounds only (e.g., "every indicator gets at least 5%").

With no information, weights are uniform on W ("Bayesian" in Hovanov's and SMAA's sense). With constraints, weights are uniform on the restricted set W′.

**Preference profile** = a named, versioned set of these constraints (e.g., "cheap and feasible": path_to_human ≥ novelty ≥ effect_level; "fundamental": mechanism, informativeness, novelty ≥ cost). One run per profile; profiles are reported with results ([design notes, section 2.1 Aggregation without explicit weights: АСПИД / МРСП (proposed, 2026-10-15)](working-notes.md)).

## 3. Weight sampling (Tervonen, Lahdelma 2007, section 3.2)

| Preference information | Method | Cost |
|---|---|---|
| none | draw n−1 uniforms in [0, 1], sort ascending, prepend 0 and append 1; weights = consecutive differences (Algorithm 2) | O(n log n) |
| complete ranking (incl. ties as equalities) | sample as above, then sort the weights to match the ranking | O(n log n) |
| lower bounds | shift: w′_j = w_j − w_min_j, sample w′ uniformly on the simplex scaled to sum 1 − Σ w_min_j, add bounds back | O(n log n) |
| upper bounds | rejection sampling (reject the whole vector if any bound is violated); acceptance can collapse: with n = 5 and w_max = 0.4 for all weights, 63.2% of vectors are rejected | grows fast with n |
| partial order, mixed constraints | **hit-and-run** MCMC, uniform over a convex polytope (Tervonen et al. 2013; R `hitandrun`); needs burn-in and thinning | linear per step |
| small n, discrete grid (Hovanov) | enumerate all weight vectors on the lattice with step 1/k that satisfy the constraints; exact but explodes combinatorially (a hierarchical example with k = 50 had ≈1.8·10⁸ vectors and switched to Monte Carlo) | exponential in n |

Recommendation: implement hit-and-run once for general linear constraints (covers every case), plus fast paths for "none", "complete ranking" and "lower bounds". Validate the sampler with the tests in section 7.

## 4. Outputs

All outputs come from one simulation pass over K iterations; in each iteration draw one weight vector and one realization of the uncertain indicator values, compute u for every hypothesis, rank them, and update counters (Algorithm 3). Use the same draws for all hypotheses (common random numbers), so pairwise quantities are consistent.

| Output | Definition | Our use |
|---|---|---|
| expected value E[u_i] and standard deviation; quantiles | over all draws | Hovanov's main outputs; pool-independent if scales are fixed |
| pairwise winning index / dominance probability P(u_i > u_j) | share of draws where i beats j | Hovanov's dominance probability; pool-independent if scales are fixed |
| rank acceptability b_i^r | share of draws where i has rank r | portfolio and top-k selection |
| acceptability a_i = b_i^1 | probability of being best | — |
| **P(i in top-k)** = Σ_{r ≤ k} b_i^r | probability of being among the first k | **entry threshold to judges** ([design notes, section 2.3 Co-Scientist debates, and where we might need a judge (2026-10-19)](working-notes.md)) |
| central weight vector w_i^c | mean of the weight vectors under which i is ranked first | explanation: "which priorities favour this hypothesis" |
| confidence factor p_i^c | probability that i is first when the central weights w_i^c are fixed and only the data vary (Phase 2, Algorithm 4) | whether the data are precise enough to separate i from the rest; low for hypotheses with many unknowns |
| decision entropy (optional) | entropy of the rank or choice distribution (R `smaa`) | overall decisiveness of a run |

Rank-based outputs (b_i^r, a_i, P(top-k)) depend on pool composition by definition; values and pairwise probabilities do not (with fixed scales). Report both.

**Across profiles:** P(top-k) per profile; a hypothesis that stays above the threshold in every profile is a robust candidate; profile-specific winners show what each goal would pick.

## 5. Accuracy and run size (Tervonen, Lahdelma 2007, section 5)

- Rank acceptabilities and confidence factors are proportions; for error δ with 95% confidence: K = 1.96² / (4δ²). δ = 0.01 → K = 9,604. Typical practice: 10⁴–10⁶ iterations.
- Central weights for hypothesis i: K = 1.96² / (a_i · 4δ_w²); hypotheses with small acceptability need many more iterations (usually irrelevant: central weights matter only for contenders).
- Report the Monte Carlo interval for every probability: p ± 1.96 √(p(1−p)/K).
- Cost: Phase 1 is O(K · m · n) for m hypotheses and n indicators (×log m for ordinal mappings); 10⁴ iterations for 10 alternatives × 8 criteria took under a second in 2007. Thousands of hypotheses are feasible.
- Store K, the random seed, the profile version and the indicator mapping with every result (the R package stores K as an attribute).

## 6. Interface sketch

```python
IndicatorSpec(id, kind="ordinal"|"cardinal", levels|bounds, higher_is_better: bool,
              ordinal_mapping="smaa_o"|"equal_steps", unknown_policy="uniform")
Profile(name, version, constraints=[Order("a", ">=", "b"), Equal("a", "b"), Bounds("a", lo, hi), Prefer(...)])   # Prefer: section 6a
aggregate(values: dict[hyp_id, dict[ind_id, float | Level | Unknown]]   # Level: ordinal level index (SMAA-O maps it per draw), indicators, profile,
          K: int, seed: int, k_top: int) -> AggregationResult(
    expected, std, quantiles, pairwise, rank_acceptability, p_topk,
    central_weights, confidence_factors, meta={K, seed, profile_version, mapping})
```

## 6a. Expert pairwise choices as weight constraints

Source: [design notes, section 2.5 Expert in the loop (agreed 2026-10-19)](working-notes.md), point 3.

- **Constraint.** An expert choice "A is at least as good as B" under a profile becomes Σ_j w_j (q_Aj − q_Bj) ≥ 0, a linear constraint on the weights. It is stored in the profile as `Prefer("H-A", ">=", "H-B", by, at)`; the profile version increases. Sampling uses hit-and-run (section 3), since the constraint is not a simple order on weights.
- **Unknown values.** If A or B has unknown indicator values, the constraint depends on the draw. MVP: substitute the expected value of the unknown (midpoint of its range, or the mean of the SMAA-O mapping for ordinal levels) and mark the constraint `approximate`. The exact treatment (constraint must hold for the drawn values) is an open point.
- **Which pairs to ask.** Among the top (P(top-k) above the judge threshold), pairs with P(A > B) closest to 0.5; ties broken by the share of the admissible weight set the answer would cut (estimate from the current sample: share of draws violating each possible answer). Ask one pair at a time and re-run, since each answer changes the remaining uncertainty.
- **Contradictions.** If the constraints leave an empty admissible set (hit-and-run finds no starting point; check with a linear program), report the minimal set of conflicting choices and raise `criterion_gap` ([design notes, section 2.3 Co-Scientist debates, and where we might need a judge (2026-10-19)](working-notes.md)). Never drop an answer silently.
- **Reporting.** Results are reported with and without expert constraints (autonomous mode), together with the number of questions asked.
- **Background.** Preference disaggregation / robust ordinal regression: Greco, Mousseau, Słowiński 2008, EJOR 191: 416–436, doi:10.1016/j.ejor.2007.08.013 (not read yet).

Interface addition:

```python
Prefer(a: hyp_id, op=">=", b: hyp_id, by: str, at: date, approximate: bool = False)
check_feasible(profile, values, indicators) -> Feasible | Infeasible(conflicting=[Prefer, ...])
next_pair(result: AggregationResult, k_top: int) -> tuple[hyp_id, hyp_id]
```

## 7. Tests

- **Uniform simplex:** with no preference information, E[w_j] = 1/n (within Monte Carlo error).
- **Complete ranking:** expected weights equal rank-order centroid weights, w_j = (1/n) Σ_{k=j..n} 1/k (the centroid of the ranked simplex region); a direct check of the sorting method and of hit-and-run.
- **Dominance:** if q_i ≥ q_j on every indicator and > on at least one, with no unknowns, then P(u_i > u_j) = 1.
- **Symmetry:** identical indicator vectors and no preference information → equal acceptabilities.
- **Unknowns widen spread:** replacing a known value by unknown never reduces the standard deviation of u_i.
- **Monte Carlo error:** repeated runs with different seeds stay within the stated intervals.
- **Pool independence:** with fixed scales, adding a hypothesis does not change E[u_i] or P(u_i > u_j) of the others (it may change ranks).
- **Expert constraint:** after adding `Prefer(A, ">=", B)` with no unknowns, P(u_A ≥ u_B) = 1 within Monte Carlo error; two opposite strict choices on the same pair → `Infeasible` listing both.

## 8. Open points

- Hovanov's monograph (1996) was not accessible: his families of normalizing functions (possibly nonlinear) are unverified; we use fixed linear scales and SMAA-O mappings.
- Additive aggregation double-counts correlated indicators (e.g., effect_level and robustness, both driven by the same evidence); check correlations on real cards and, if needed, merge or constrain weights.
- Dependent uncertainties between indicators (SMAA supports joint distributions; Lahdelma et al. 2004) are out of scope for the MVP.
- Bounds of the fixed reference scales for the cardinal indicators (effect size, late start; spec 12). Cost and time became the ordinal `path_to_human` (2026-10-20).

# Pilot: hypotheses tested by computation (plan, 2026-11-08)

Status: plan for the user's review; no code, no model calls yet.

## Why

The trial-outcome label is noisy (blinding and placebo predict "positive" as well as anything we compute; the models' "will it
be confirmed?" reaches 0.76-0.80 partly through knowledge of past trials). A hypothesis that a fixed analysis of open data can
test gives a label in days, with no leakage: the analysis is run after the scores are frozen. It measures "is there the
predicted signal in the data", not "does the intervention work in people", so it is a second, cleaner calibration, not a
replacement for trials.

## Type of hypothesis

"Compound X shifts the gene expression of tissue Y towards the young state" (signature reversal).

- **Compound signatures:** LINCS L1000 (CMap), consensus signatures per compound across cell lines (level 5), public.
- **Ageing signatures:** Tabula Muris Senis (mouse; bulk and single-cell, many tissues, 1-30 months) and GTEx (human, 54
  tissues, age in decades); a per-tissue old-vs-young signature computed once, fixed before the pilot.
- **Test (fixed before running):** connectivity between the compound's signature and the inverted ageing signature of the
  tissue (weighted connectivity score as in CMap, or a rank correlation over the landmark genes); significance against
  1,000 random compounds of the same library and a gene-label permutation; "reversal" = connectivity below the 5th percentile
  of random compounds (one-sided), the same threshold for every hypothesis.
- **Positive control, known before:** compounds that extended mouse lifespan in the ITP or DrugAge (rapamycin, acarbose,
  17-α-estradiol, NDGA, canagliflozin, ...) should reverse ageing signatures more often than random compounds. If they do not,
  the test itself does not measure what we want and the pilot stops there.

## Hypotheses

- 30 hypotheses: compound × tissue pairs with a written rationale (mechanism chain), the same form as our cards.
- Sources: 10 written by a model (one prompt: "a compound in LINCS that would reverse ageing in tissue Y, with a mechanism"),
  10 by a divergent generator (Omega-Point-like roles), 10 random pairs as a floor; the analysis is the same for all 30.
- Novelty check before freezing: no hypothesis whose exact compound × tissue reversal is already published (PubMed search by
  code; the dropped ones are listed).

## What is scored before the analysis (frozen with a hash)

1. Our method v3.4 on each hypothesis (P, support share, novelty, the ASPID profiles), with the literature cut-off = today.
2. The baseline "will it be confirmed?" by two model families (as specs/llm-consensus-2026-11-07.yaml).
3. Optional: Argon's reading of the same hypotheses (blind).

## Outcome and test

- Label: reversal yes / no by the fixed test.
- Primary: tied AUC of P (and of the evidence profile's score) against the label; the same for the model baseline; paired
  bootstrap of the difference.
- Secondary: does novelty predict a lower hit rate (popularity trap); do model-written hypotheses beat random pairs.
- With 30 hypotheses only a large difference is visible; if the pipeline works, a second round of 100 is cheap.

## Cost and time

- Data: free (LINCS via clue.io or the GEO deposit, Tabula Muris Senis and GTEx downloads; no keys except possibly clue.io).
- Model calls: generation about 0.2 USD; our method about 1.7 USD for 30 hypotheses; the model baseline about 0.1 USD.
- Work: the signature code and the positive control first (about two sessions), then generation, freezing, the run.

## Risks

- Cell-line signatures are far from tissues; the positive control decides whether to go on.
- The test may be dominated by a few generic responses (proliferation, stress); checked by comparing with random compounds.
- Our method reads abstracts for links like "X inhibits mTOR in liver"; for many compounds the literature is thin.

## Later types (same pipeline)

- Mendelian randomisation: "genetically lower plasma protein Z -> longer parental lifespan" (pQTL and longevity GWAS via
  OpenGWAS, a free key); closest to the "right target" of AstraZeneca's 5R; many protein-lifespan pairs are already published,
  so the novelty check matters more.
- NHANES with linked mortality: "marker X predicts mortality beyond age".
- Epigenetic clocks on GEO data of completed interventions (few sets).

## Questions for the user

1. Start with signature reversal, or with Mendelian randomisation (closer to human biology, more prior work)?
2. Mouse ageing signatures (Tabula Muris Senis), human (GTEx), or both?
3. Who generates the 20 non-random hypotheses: our models, Argon, or the Omega Point engine of Eternal Search (it is
   published as a local skill)?

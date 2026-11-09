# The test model of a hypothesis: how the decisive experiment will test it (plan, 2026-11-09)

Status: plan for the user's review; no code, no calls. User decisions of 2026-11-09: design rigour enters I as a part
(a separate indicator may be tested later); the "probability of a positive report" is not shown until it is shown to
mean something.

## Why

The decisive experiment decides what a result will mean. The method describes it only as a compressed card (system, design,
control label, n, primary outcome) and one d per alternative. What it does not have: which arms and measurements the trial
has, what the hypothesis and each competitor predict in each of them, what a positive or null result would then mean, and
how much the design itself can be trusted. Earlier attempts to forecast the trial's success from its design failed
(experiment forecast 0.55; protocol layers: only room for bias, 0.62) because design mostly moves the chance of a
positive report through bias; this plan does not forecast success: it describes the test.

## The layer (one model call per trial, from the registry text; DeepSeek)

1. **Arms and measurements**: the named arms and controls (verbatim phrases), the primary and secondary outcomes with their
   time points, who is blinded. Code checks every phrase against the registry text.
2. **Prediction matrix**: rows = the hypothesis and each alternative (the proposed ones and the checklist kinds of
   propose_alternatives/v2); columns = the comparisons the design allows (arm vs arm on an outcome, a mediator that is
   measured); each cell + / − / 0 / not tested. d of an alternative = 1 when some column has opposite signs for H and the
   alternative, 0.5 when a measured mediator bears on it without an opposite sign, 0 otherwise — computed by code from the
   matrix, not stated by the model (replaces judge_alternatives).
3. **Decision criteria** (card spec section 8c): what a positive result means (which alternatives fall, which remain),
   what a null result means, what a mixed one means; written from the matrix by code with fixed wording.
4. **Design rigour R** (0-1, four items read from the registry text, each with a verbatim phrase): an active or
   stimulus-matched control; a dose, timing or blocker contrast that tests the mechanism; blinded outcome assessment; a
   measured marker of target engagement. Enters I as a part (below).
5. **For the reader of the report**: one paragraph "how this hypothesis will be tested and what each result would teach",
   built from 1-3; no probability of success.

**I with rigour.** Today I = min(1, Σ a·d / 1.5). Candidates, compared on the checks below before one is adopted:
(a) I = min(1, (Σ a·d + w·R) / 1.5), w = 0.5 (rigour worth a third of the cap); (b) I = 1 − (1 − I_alt)(1 − R/2) (rigour
can raise I to at most 0.5 alone). Both leave I = 0 for a design with no supported alternative cut off and no rigour item.

## Checks (dev / holdout split by SHA-1 as for judge_alternatives; fixed in a spec before any call)

- **d from the matrix vs Argon's d** (pack 6, 293 alternatives): weighted κ next to judge_alternatives v2 (0.35 holdout).
- **Missing competitors**: the checklist rows of the matrix vs Argon's missing alternatives (pack 6, hand-labelled on the
  holdout as before).
- **Design changes**: the item the matrix shows as the cheapest separating arm vs Argon's "best change" per trial (pack 6),
  hand-labelled agree / partly / no.
- **Failure reasons visible before the trial** (Argon pack 4, 74 calibration trials, post hoc labels): do the rigour items
  and the matrix flag the reasons Argon called visible before (dose / exposure, control improving, endpoint, bias)?
  Reported only, not used to decide (post hoc, and these trials are no longer used for blind checks with Argon).
- **Rigour and the outcome**: R against trial outcomes on the calibration is expected to run the other way (open trials
  are more often positive); reported to show what R is not, never used to tune it.
- **Later**: the 60 prospective trials when their outcomes arrive (frozen scores first).

## Cost (DeepSeek V4.1 Flash, off-peak)

One call per trial: the registry text (about 1.2 k tokens), the alternatives, the chain (about 1 k) in; the matrix and
criteria (about 1.5 k) out: about 0.0015 USD per trial; 59 prospective + 73 calibration trials about 0.2 USD; one prompt
revision on dev about 0.05. In all about 0.25-0.3 USD.

## Questions for the user

1. Which form of "rigour as a part of I", (a) additive or (b) multiplicative, or both computed and the choice made on the
   checks?
2. Should the matrix replace judge_alternatives for d at once if its κ with Argon is not lower, or only when higher?

# Evidence-guided evolution of hypotheses: protocol (declared before the run, 2026-10-22)

**Question.** Does refining the top hypotheses with what their verification found give children that rank among the
parents, under the same rules? No guarantee is claimed, and a run in which no child ranks high is reported in the
same way as one in which several do.

**Setup (fixed now).**
- Parents: the ten hypotheses of the mouse example (`runs/neg_v2/.../g003.reapplied.json`, literature up to 2013-11-18),
  verified with the rules of 2026-10-22 and with the informativeness indicator added (`runs/evolution/g003.parents.json`,
  9 calls; every parent has informativeness 0: their decisive experiment is a plain survival comparison).
- Rounds: 3. Each round the top 4 hypotheses by the profile "Приоритет: проверенные данные" that have not been parents
  become parents (children can parent in later rounds); each parent gets 2 children.
- A child is a refinement of one kind, driven by a verified fact: `narrow_context`, `resolve_conflict`, `add_mechanism`,
  `test_alternative` (prompt `evolve_hypothesis/v1`). It keeps the intervention, does not copy the parent, and is
  rejected by code when it does not.
- Children go through the same pipeline as every hypothesis: card, admission, verification (same cut-off date), the
  alternatives, informativeness, rules as of this date; then all hypotheses are ranked together
  (K = 10 000, seed 0, three profiles). Models: writer Gemini (CometAPI), verifier DeepSeek V4.1 Flash.
- Budget: at most 200 model calls in total (proposals, verification, informativeness); the run stops when it is spent.
- One run. A technical failure (provider errors) may be repeated with the same configuration and is reported.

**Primary criterion.** At least one child ends in the top 3 of the profile "Приоритет: проверенные данные" in the final
ranking, and its P(top-3) is at least that of its parent.

**Reported in any case (descriptive).** Places and P(top-3) of every child and its parent; children by kind; the share of
children whose main claim is supported or contested, whose informativeness is at least 1, whose gate filtered them;
calls per round; the lineage on the site.

**Limits, stated before the result.**
- Circularity: children are written from the verifier's findings and ranked by the same verifier and indicators, and the
  informativeness indicator rewards a control written into the experiment. The run shows whether guidance by checks
  raises the scores, not whether the children are true. There is no external validation in this run.
- Informativeness is graded on what the text of the child states; a child that names a control it never states gets no credit.
- Nothing is changed after the result: no other seed, no hand selection of children, no change of rules or of the criterion.

## Result (added after the run, the protocol above is unchanged)

One run, 24 children over three rounds, 168 model calls of the 200 allowed (counted from the log: the in-run counter of that
version dropped the children's verification calls from round 2 on; fixed in `hyparena/card/evolve.py`), about 1.0 M input
tokens, 12 minutes. Primary criterion: formally met by one child (place 3, P(top-3) 0.155 against 0.149 of its parent),
but both differences are within the Monte Carlo error (±0.01) and three more children share the place (expected scores
0.1851 to 0.1855); the first two places stay with the parents (P(top-3) 0.62 and 0.53). The scores of the children rose
because of the informativeness indicator (19 of 24 children have it at 1 or more, all parents 0); the main claim is
supported or contested for one child, unverified for 19; four children did not reach the ranking (2 filtered, 2 card
failures). Details: reference, "Эволюция гипотез и информативность".

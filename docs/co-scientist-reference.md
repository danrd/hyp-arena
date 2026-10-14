# Co-Scientist reference notes

Source: Gottweis et al., "Accelerating scientific discovery with Co-Scientist" (Nature revision, [arXiv:2502.18864](https://arxiv.org/abs/2502.18864)). It is a later version than the February 2025 preprint ("Towards an AI co-scientist") and uses Gemini 2.0 models. Everything below was read from the paper text; section names are given so claims can be checked. Google has not released code; the paper includes agent pseudocode (Supplementary Note 8) and all prompts (Supplementary Note 9).

## 1. Hypothesis format

There is no fixed schema.

- **Input:** a free-text research goal (from a sentence to tens of thousands of tokens, optionally with prior-publication PDFs). The system parses it into a *research plan configuration* with three parts: **Preferences**, **Attributes** (e.g. "Novelty, Feasibility") and **Constraints** (e.g. "should be correct, should be novel"). Supplementary Note 10.1 has an example.
- **Output:** free-form prose for domain experts. The generation prompt asks to describe the hypothesis "in detail, including specific entities, mechanisms, and anticipated outcomes". In the ALS example (Note 10.2) the sections are: Introduction, Recent findings and related research, Hypothesis, Rationale and specificity, Experimental design and validation. The debate-based generation prompt ends with the word "HYPOTHESIS" followed by "a concise and self-contained exposition".
- **Configurable output formats:** the output can be constrained to a researcher-preferred format. Drug-repurposing hypotheses were rendered as NIH Specific Aims pages using constrained decoding, and the Meta-review agent produces research overviews in grant formats.
- **Attached reviews:** each hypothesis carries its reviews, which the ranking step reads. The Generation agent also summarizes and categorizes each hypothesis.

## 2. Judges

- **No panel of separate models.** All agents use one model family (Gemini 2.0 in the paper). A comparison is one LLM call. A "panel of domain experts" in the debate prompt is one model role-playing.
- **Two comparison modes (Ranking agent):**
  - top-ranked hypotheses: multi-turn "scientific debate", typically 3 to 5 turns, at most 10;
  - lower-ranked hypotheses: single-turn pairwise comparison.
  Both end with "better idea: <1 or 2>".
- **Reviewers (Reflection agent)** produce the reviews attached to hypotheses:
  - *initial review*: correctness, quality, novelty, preliminary safety; no external tools, used to discard obviously flawed or non-novel ideas;
  - *full review*: the same criteria with literature search;
  - *deep verification*: decomposes the hypothesis into assumptions and sub-assumptions and checks each independently;
  - *observation review*: whether the hypothesis explains existing observations; verdict is one of "already explained / other explanations more likely / missing piece / neutral / disproved";
  - *simulation review*: step-wise simulation of the mechanism or experiment to find failure scenarios;
  - *recurrent (tournament) review*: reviews adapted to patterns found in tournament debates.
- **Other judge models** (o3-mini, o1-preview, Gemini 2.0 Pro, Gemini Flash Thinking) appear only as external evaluators in the paper's LLM-as-a-judge evaluation, not inside the system.
- **Not found in the text:** the number of hypotheses and tournament matches per research goal, and the number of reviewer calls per hypothesis.

## 3. Criteria

- **Five default criteria** (Methods, overview): alignment with the research goal, plausibility, novelty, testability, safety. More can be configured per goal.
- **Comparison prompt:** the goal's attributes and preferences are inserted as `{idea_attributes}` and `{preferences}`. The prompt tells the judge to disregard any numeric scores in the attached reviews because they may not be comparable across reviews.
- **Debate prompt** adds: potential for correctness/validity, utility and practical applicability, sufficiency of detail and specificity, novelty and originality, desirability for implementation.
- **Result:** a **single Elo rating** per hypothesis (initial value 1200). Feasibility can be one of the configured attributes, but there is no separate rating per axis.

## 4. Tournament mechanics

- Match pairing prefers (1) hypotheses similar to each other, using the Proximity agent's graph, and (2) newer and top-ranked hypotheses.
- The Evolution agent never edits a hypothesis. It creates new ones (grounding, feasibility improvement, inspiration, combination, simplification, out-of-the-box), and each must win its own matches. This protects top-ranked hypotheses from flawed edits.
- The Meta-review agent summarizes recurring review and debate patterns into feedback that is appended to other agents' prompts in the next iteration (no fine-tuning).

## 5. What the paper reports about judge reliability

- **Debate vs. simple comparison:** the debate prompt is clearly more accurate for top-vs-top pairs (1800 matches with both ideas highly rated). On 2000 general matches, the two prompts are on par with Gemini Flash 2.0 and debate is better with Flash 2.5.
- **Position bias:** with swapped order (A vs. B and B vs. A, 2000 matches), the simple prompt showed a "second player advantage"; the debate prompt almost eliminated it.
- **Search for novelty:** on published (non-novel) ideas, the review without search gave novelty 6.14/10; with search, 2.38/10.
- **Elo vs. truth:** higher Elo correlates with higher accuracy on GPQA diamond, but the authors state the Elo metric is auto-evaluated and not based on independent ground truth. The AUC of review scores for predicting correctness is modest (about 0.64 to 0.65 on GPQA).
- **Expert evaluation:** 11 goals, four systems compared; Co-Scientist had mean preference rank 2.36, novelty 3.64 and impact 3.09 out of 5. The authors call these subjective assessments.

## 6. Implications for this project

- Their hypothesis format is minimal. A structured schema (see `docs/approach.md`, section 9) makes comparison and explanation easier.
- One Elo over configurable criteria differs from our plan of separate promise and feasibility ratings.
- One model family means correlated judge errors; an ensemble of different models is a justified improvement.
- Search-grounded novelty review is supported by their ablation and is part of our pipeline.
- Judge quality is only modestly validated, so expert-labelled data is needed to measure it.

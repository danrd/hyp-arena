# Bio Arena (bioarena.ru) and our approach

Bio Arena is an open tournament of hypotheses on ageing and healthy lifespan. Anyone
submits a text; an LLM checks it, builds an evidence dossier from the literature, and an LLM judge compares
hypotheses in pairs; a Bradley–Terry model turns the matches into a ranking with uncertainty. Everything is
published through the site's JSON API: texts, dossiers, the judge's prompt, both verdicts of every match with
reasons, and a log of model calls. This note describes how it works (from the API and the front end, read
2026-10-19), what we exported, and how it relates to our method.

## How it works

| Stage | What happens (model in the snapshot) |
|---|---|
| Submission | text up to 10,000 characters and an author name; the same text returns the same submission; semantic duplicate check (`dedup-v1`) |
| Moderation | a classifier (`openai/gpt-6-luna-decisions`) gives `acceptable` or a rejection category with probabilities |
| Evidence dossier (`evidence-v1`, schema `dossier-v2`) | `openai/gpt-6.1-sol` (high reasoning): extracts the author's claims with verbatim quotes, the main hypothesis, the author's experiment and search queries; searches Europe PMC (and trial registries); a separate model decides on each candidate source (relevance, study type); up to 30 sources, full texts up to 20,000 characters each; analysis: mechanism, supporting and opposing evidence with quotes and source ids, an AI-proposed experiment with assumptions and limitations (kept apart from the author's), potential benefit, uncertainties; a consistency check, repaired if needed |
| Matches (`matches-v1`) | the judge (`openai/gpt-6.1-sol`, high reasoning) sees both dossiers and answers "which should be investigated first?" with A or B, a confidence and a Russian reason; each pair is judged in both orders, each order independent |
| Resolution | both orders agree → that winner (`agreement`); one verdict with high confidence suffices (`high_confidence`); orders disagree → the more confident one (`confidence_split`), or a random winner when the confidences are equal (`random_split`) |
| Ranking (`bt-v1`) | Bradley–Terry with ridge regularization (λ = 1, Newton-CG), ratings on an Elo-like scale (center 1000, scale 400) with standard deviations and intervals; adaptive scheduling: new hypotheses calibrate (up to 20 matches), contenders get more matches until their rating is precise (`precision`), the rest stop early (`low_priority`) |

**Judge criteria** (`judge_instructions.txt` in the export): mechanistic plausibility, supporting and opposing
evidence, potential benefit for human healthy lifespan, and the nearest convincing verification experiment
("feasibility means the next discriminating experiment"). Large potential benefit may compensate for lower
certainty if the mechanism is plausible and the experiment convincing. A five-step procedure for broad versus
local hypotheses (causal substance; justified scope; experiment matched to the claim; learning from positive and
negative results; the trade-off). No absolute scores, no ties; model-organism findings are not proof of human
benefit; AI-proposed experiments are not credited to the author.

## The export (`data/bioarena/2026-10-19/`)

`python -m hyparena.tools.bioarena --out data/bioarena/<date>` (`hyparena/tools/bioarena.py`); read-only, public
API, three requests at a time (a hypothesis page takes the server 7–10 s).

| File | Contents |
|---|---|
| `ranking.json` | the ranking snapshot of 2026-10-17 12:49 UTC (id `0591909d…`), all 985 hypotheses with state, rating, interval, wins and losses, planned and completed matches; author table |
| `hypotheses.jsonl.gz` | one object per hypothesis: text, status, moderation, dossier (claims, sources, selection decisions, analysis), tournament and ranking fields, pipeline stages, call statistics |
| `matches.jsonl.gz` | 6,822 matches: participants, both evaluations with winner, confidence and reason, resolution |
| `hypotheses.csv` | flat summary per hypothesis |
| `judge_call_example.json`, `judge_instructions.txt` | one full judge call (instructions, the two dossiers as input, the verdict) |
| `status.json` | service state, queue counts, position-bias statistics, recently rejected submissions |

**Snapshot figures:**
- 985 accepted hypotheses from 18 authors, submitted 14–17 October 2026; median text 1,630 characters. Two AI authors dominate: "Кайрос (ИИ-агент)" (501) and "Astra Средний" (338); the rest are model names, ChatGPT variants, an organisation and individuals.
- Tournament: 343 participants, 334 rated in the snapshot, the other 641 waiting for their dossier (608 dossiers are queued; processing is paused). 301 dossiers are verified; median 10 sources each.
- 6,818 completed matches (median 11 per rated hypothesis, up to 167 for the leaders). The two orders agree in 6,247 matches (91.6%); 571 splits, 247 of them settled at random. The first position wins 50.0% of evaluations, so there is no position bias overall.
- Median width of the rating interval: about 400 points, so most of the middle of the ranking is not separated.
- Cost: about 42,000 model calls and 535 million tokens so far (the call statistics of the hypothesis pages).
- Author means over rated hypotheses range from about 1,400 (ChatGPT, gpt-6-astra) to about 400; the top two hypotheses are by "Кайрос (ИИ-агент)" (1896, 1828).

## Relation to our approach

| Bio Arena | Ours (method v2, `docs/rules-method.md`) |
|---|---|
| dossier: the author's claims with quotes, supporting and opposing evidence with quotes, uncertainties | card: declared claims in a closed vocabulary with verbatim spans; verified layer with evidence records, statuses computed by rules |
| quotes and consistency checked by an LLM | quotes checked verbatim by code; statuses, gate, evidence profile by code |
| one judge decides everything, pairwise, in both orders | indicators from the card by rules; LLM judges only for the top (stage C) |
| criteria inside one prompt (plausibility, evidence, benefit, next experiment) | criteria as separate indicators with an importance order per profile (АСПИД/SMAA) |
| Bradley–Terry with intervals, adaptive scheduling | our ladder steps L1–L4 use per-criterion Bradley–Terry; the Co-Scientist baselines use Elo and TrueSkill |
| no filter of refuted hypotheses; a contradicted hypothesis can still win on potential benefit | the gate filters refuted outcome, mechanism or premise claims before ranking |
| random winner when the two orders disagree with equal confidence | ties count half; uncertainty is kept in the aggregation |

**What it gives us:**
1. **A large external pool in our domain**: 985 real texts (mostly AI-generated) for the card pipeline, with ready dossiers to compare our verifier against (sources, supporting and opposing evidence, both with quotes).
2. **A second opinion on the ranking**: 334 rated hypotheses with intervals from about 6,800 judge comparisons. Agreement between our ranking and theirs (rank correlation, and whether our top lands in their top) is a useful check, though neither is ground truth: theirs is one judge model's preference.
3. **Judge data**: 13,600 verdicts with reasons and confidences in both orders, usable to study consistency (8.6% split) and to calibrate our own judges.
4. **Design points to borrow or to test against**: the separation of the author's experiment from the AI-proposed one; the selection step for sources with recorded reasons; adaptive scheduling (precision for contenders, early stop for the rest), which matches our use of P(top-k) as the entry threshold.

**Caveats:** the snapshot is mid-tournament (two thirds of the hypotheses have no rating yet); ratings of hypotheses with few matches have wide intervals; the pool is dominated by two AI authors, so author comparisons are uneven.

Ranking these hypotheses with our pipeline is a later step, when the pipeline is settled.

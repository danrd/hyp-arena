# Archive

Documents kept for their ideas and history, not as a description of the current system. The current method is the
[manual](../../docs/method-v3-manual.md); every check is a file in [`specs/`](../../specs) with its result; deferred work is in
[`docs/backlog.md`](../../docs/backlog.md); hand-offs between sessions are in [`archive/handoffs/`](../handoffs/).

| File | What it is | Why kept |
|---|---|---|
| [method-history.md](method-history.md) | Earlier rules of method v3 (v3.0-v3.6): old weight tables, the Beta strength, P (non-refutation), the earlier profile orders, the first evolution run, the discrete levels, the worked example under each version, the validation tables of 2026-11-07 | how each rule came to be; the worked examples are still checked by `tests/test_manual.py` |
| [spec/method-v3.md](spec/method-v3.md) | The Russian specification of v3 with the user's decisions of 2026-11-02 … 11-07 | the reasoning behind the mechanism chain and the axes |
| [spec/mechanism-chain-draft.md](spec/mechanism-chain-draft.md) | The paper runs that led from v2 to the mechanism chain | why a hypothesis is valued for its mechanism |
| [spec/working-notes.md](spec/working-notes.md) | Design notes of 2026-10-19 (v2) | early decisions (two layers of the card, the closed relation vocabulary) |
| [spec/hypothesis-card-examples.md](spec/hypothesis-card-examples.md) | Hand-built v1 cards | examples of the card format |
| [rules-method.md](rules-method.md) | Method v2: verified card → rule-based indicators → aggregation | the baseline that v3 replaced (calibration AUC 0.46) |
| [approach.md](approach.md), [architecture.md](architecture.md) | The Co-Scientist-style approach and multi-agent graph | the Elo / TrueSkill baselines still in the code |
| [comparison.md](comparison.md), [negative-sampling.md](negative-sampling.md), [evolution-experiment.md](evolution-experiment.md) | Protocols of the v2-era tests | their criteria are in `specs/whole-system/validation-criteria.yaml` |
| [demo.md](demo.md) | The Gradio demo of v2 | the demo app (archived code: [`archive/code/`](../code/README.md)) |
| [bioarena.md](bioarena.md), [co-scientist-reference.md](co-scientist-reference.md) | Notes on Bio Arena and on how Co-Scientist works | background of the comparison lines (`docs/backlog.md`) |
| [itp_2010_changes_after_first_run.csv](itp_2010_changes_after_first_run.csv) | Changes of the ITP 2010 pool after its first run | history of `specs/whole-system/itp-backtest-2010.yaml` |

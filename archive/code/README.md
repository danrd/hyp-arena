# Archived code

Code of method v2 that the current method (v3) does not use, and helper modules no current check calls. Kept for reference; not installed with the package and not
tested. The git history has every earlier version.

| File | What it was | Documentation |
|---|---|---|
| `app.py` | The Gradio demonstration page of method v2 (paste or generate hypotheses, get a pairwise-tournament ranking) | [`archive/docs/demo.md`](../docs/demo.md) |
| `sim.py` | A simulation of pair-selection strategies for a pairwise tournament with a noisy judge (method v2 ranked by pairwise comparisons; v3 does not) | its docstring |
| `check_examples.py` | Checks of the v2 normaliser and verifier against the worked card examples | [`archive/docs/rules-method.md`](../docs/rules-method.md) |
| `metrics.py`, `multitest.py`, `survival.py`, `swap_test.py` | Benchmark metrics, multiple-testing corrections and e-values, survival analysis, the name-swap diagnostic of the v2 checks (`specs/whole-system/validation-criteria.yaml`); unused by method v3 | their docstrings; tests in [`tests/`](tests/) |

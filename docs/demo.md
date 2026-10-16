# Demonstration interface

A small page for showing the pipeline: paste or generate a few hypotheses and get a ranking. The interface is in Russian; prompts stay in English, hypotheses can be in any language, and the research overview is written in Russian.

```bash
pip install -e ".[demo]"
ALLOW_PAID=1 python -m hyparena.app          # http://127.0.0.1:7860; COMET_API_KEY must be set for the paid models
python -m hyparena.app --share               # also a temporary public link (Gradio, about 72 hours)
```

**Tabs.**
- **Готовый пример** (saved example): a saved run from `data/demo/*.json`. It opens instantly, which makes it suitable for a demonstration.
- **Новый прогон** (new run): pasted hypotheses (a numbered list or blocks separated by blank lines; the writer's family can be given, so judges avoid it) or generated ones (3–8, for a stated goal). The run uses our full method (L4), two cycles. Models can be the cheap paid set, the free set, or no models at all (fake LLM, to check the interface). Progress is shown by stage.

**What a run costs.** Five pasted hypotheses on the cheap paid models: see the saved example for the exact numbers (about 50–60 calls and a few minutes). Small pools play every pair first (`round_robin_max`, 8 by default), then the usual selection.

**The result** shows:
- the place and 90% rank interval;
- the expected score with its spread (aggregation by order of importance, based on МРСП);
- per criterion, the probability of beating an average hypothesis, with an interval;
- a matrix "probability that A is above B" for the top;
- per hypothesis: the text, the declared card, the literature with links and epistemic types, the reviewers' remarks, every comparison with the judges' reasons;
- the research overview.

It can be downloaded as a standalone HTML page and as JSON.

**Without the app:** `python -m hyparena.showcase --paste file.txt --out result.json --html result.html` (or `--goal … --generate 5`), and `--render result.json --html page.html` to turn a saved result into a page.

**Embedding.** The page can be embedded with an iframe in slides that run in a browser (reveal.js, Google Slides via a link, or an HTML deck), or opened from a link: locally, through `--share`, or after deploying the app to Hugging Face Spaces (keys as Space secrets). A static page from `--html` needs no server at all.

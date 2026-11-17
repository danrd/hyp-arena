"""Novelty by absence for the hypotheses of a generation round (specs/evolution/generation-comparison-2026-11-16-pilot.yaml,
novelty_by_absence_2026_11_17): one card per hypothesis by the pipeline's normaliser from claim, rationale and experiment
(paid, about 0.03 USD a text), then PubMed counts before T on the outcome pair and on every mechanism link (free). Only
numbers are printed; the cards are written to cards_<kind>.json in GEN_DIR (private).

    ALLOW_PAID=1 GEN_DIR=… python -m scripts.evolution.novelty_absence cards --kinds a bs
    GEN_DIR=… python -m scripts.evolution.novelty_absence count --kinds a bs
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from statistics import median

import yaml

CONFIG = "configs/v3-flash-n10.yaml"
THRESHOLD = 5


def _dir() -> Path:
    return Path(os.environ["GEN_DIR"])


def cards(kinds: list[str]) -> dict:
    from hyparena.card.normalizer import normalize
    from hyparena.pipeline import _client
    from hyparena.reports.usage import summarize
    cfg = yaml.safe_load(Path(CONFIG).read_text())
    client, _ = _client(CONFIG, False, 100)
    out, log = {}, []
    for kind in kinds:
        f = _dir() / f"cards_{kind}.json"
        done = json.loads(f.read_text()) if f.exists() else {}
        for h in json.loads((_dir() / f"answer_{kind}.json").read_text())["hypotheses"]:
            if h["id"] in done:
                continue
            text = f"{h['claim']}\n{h['rationale']}\n{h['experiment']}"
            card, problems = normalize(client, "google", text, h["id"], log=log, version=cfg.get("normalize_version"))
            done[h["id"]] = {"card": card.model_dump(mode="json") if card else None, "problems": problems}
            f.write_text(json.dumps(done, indent=1, ensure_ascii=False) + "\n")
        out[kind] = {"cards": sum(v["card"] is not None for v in done.values()), "of": len(done)}
    out["usage"] = summarize(log)
    return out


def count(kinds: list[str]) -> dict:
    from hyparena.card.models import HypothesisCard
    from hyparena.evolution.evolution_rules import pubmed_pair_count
    from hyparena.scoring import rules_v3 as r3
    T = json.loads((_dir() / f"task_{kinds[0]}.json").read_text())["T"]
    res = {"T": T, "threshold": THRESHOLD, "arms": {}, "per_hypothesis": {}}
    for kind in kinds:
        done = json.loads((_dir() / f"cards_{kind}.json").read_text())
        outc, untested, mech_new, not_counted = [], 0, 0, 0
        for hid, v in done.items():
            if not v["card"]:
                res["per_hypothesis"][hid] = {"card": False}
                continue
            card = HypothesisCard.model_validate(v["card"])
            mf = card.main_factor if isinstance(card.main_factor, dict) else (card.main_factor.model_dump() if card.main_factor else {})
            iv = mf.get("label") or (card.pico.intervention[0].label if card.pico.intervention else "")
            n_out = pubmed_pair_count(iv, card.pico.outcome.metric if card.pico.outcome.metric != "unknown" else "", T)
            chain = r3.chain(card)
            outs = {c.id for c in r3.outcome_group(card, chain)[0]}
            mech = [pubmed_pair_count(c.subject.label, c.object.label, T) for c in chain if c.id not in outs]
            if n_out is None:
                not_counted += 1
            else:
                outc.append(n_out)
                untested += n_out < THRESHOLD
            mech_new += any(m is not None and m < THRESHOLD for m in mech)
            res["per_hypothesis"][hid] = {"outcome_pair": n_out, "mechanism_links": len(mech),
                                          "mechanism_counts": mech}
        n = len(done)
        res["arms"][kind] = {"hypotheses": n, "outcome_pair_counted": len(outc),
                             "outcome_pair_median": median(outc) if outc else None,
                             "share_outcome_untested": round(untested / len(outc), 2) if outc else None,
                             "share_with_new_mechanism_link": round(mech_new / n, 2) if n else None,
                             "outcome_pair_not_counted": not_counted}
    (_dir() / "novelty_absence.json").write_text(json.dumps(res, indent=1) + "\n")
    return res


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("cmd", choices=["cards", "count"])
    ap.add_argument("--kinds", nargs="+", default=["a", "bs"])
    a = ap.parse_args()
    if a.cmd == "cards" and os.environ.get("ALLOW_PAID") != "1":
        raise SystemExit("paid call: set ALLOW_PAID=1")
    print(json.dumps(cards(a.kinds) if a.cmd == "cards" else count(a.kinds), indent=1))


if __name__ == "__main__":
    main()

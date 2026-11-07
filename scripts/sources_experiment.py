"""Sources experiment (specs/sources-experiment-2026-11-07.yaml): the same 15 calibration trials read with abstracts (arm A,
exact-population query, configs/v3-flash-n11.yaml) and with PMC full texts where allowed (arm B,
configs/v3-flash-n11-fulltext.yaml). The cards are the frozen v10 cards, so the arms differ only in the sources. Paid.

    ALLOW_PAID=1 python -m scripts.sources_experiment run --arm A|B   # -> calibration/sources_<arm>.json
"""
from __future__ import annotations

import argparse
import json
import os

from scripts.ceiling import CAL

ARMS = {"A": "configs/v3-flash-n11.yaml", "B": "configs/v3-flash-n11-fulltext.yaml"}


def unit_ids() -> list[str]:
    import yaml
    from pathlib import Path
    spec = yaml.safe_load((Path(__file__).resolve().parents[1] / "specs" / "sources-experiment-2026-11-07.yaml").read_text())
    return list(spec["units"])


def run(arm: str) -> None:
    from hyparena.card.pipeline import run as v3
    texts = {}
    for s in (1, 2, 3, 4, 5):
        for l in open(CAL / f"texts_{s}.jsonl"):
            d = json.loads(l)
            texts[d["id"]] = d
    cards = json.loads((CAL / "cards_v3_v10.json").read_text())
    out_p = CAL / f"sources_{arm}.json"
    done = json.loads(out_p.read_text()) if out_p.exists() else {}
    for h in unit_ids():
        if h in done:
            continue
        t = texts[h]
        card = cards.get(h)
        try:
            res = v3([t["text"]], writer="human_registry", config=ARMS[arm], as_of=t["as_of"], max_calls=80, verifiers=["deepseek"],
                     cards=[card] if card else None)
        except Exception as e:
            print(json.dumps({"id": h, "error": f"{type(e).__name__}: {str(e)[:200]}"}), flush=True)
            continue
        done[h] = res
        out_p.write_text(json.dumps(done, ensure_ascii=False, default=str))
        print(json.dumps({"id": h, "outcome": res["items"][0]["outcome"], "calls": res["meta"]["calls"]}), flush=True)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["run"])
    ap.add_argument("--arm", choices=list(ARMS), required=True)
    a = ap.parse_args()
    if os.environ.get("ALLOW_PAID") != "1":
        raise SystemExit("paid: set ALLOW_PAID=1")
    run(a.arm)


if __name__ == "__main__":
    main()

"""normalize_card/v8 on the 30 calibration texts, cards only (no verification), against the v7 cards of the v3 calibration.
Criterion fixed before the call: specs/normalizer-v8-2026-11-05.yaml.

    ALLOW_PAID=1 python -m scripts.normalizer_v8_check run      # 30 normalizer calls (Gemini 3.5 Flash, configs/v3-flash.yaml)
    python -m scripts.normalizer_v8_check score                 # the measures for v7 and v8, free

Cards are saved next to the calibration in the private repository (calibration/cards_v8_check.json).
"""
from __future__ import annotations

import argparse
import json
import os

from scripts.ctgov_outcomes import KG

CAL = KG / "hypothesis_sources" / "calibration"
OUT = CAL / "cards_v8_check.json"
# texts whose summary states a reason or mechanism (hand label, 2026-11-05, before the v8 call; method-v3 card rule)
MECHANISM_STATED = ("NCT03446924", "NCT04354896", "NCT01417663", "ISRCTN87404878", "NCT02132091", "NCT00146133",
                    "NCT02787889", "NCT01576848", "NCT04981652", "NCT03817450", "NCT05609617", "NCT03142048")
MECH_LINKS = ("delivery", "engagement", "pathway")
# the fresh calibration sample (2026-11-06, hand label before the run): texts that state a reason or mechanism
MECHANISM_STATED_FRESH = ("NCT06235840", "NCT06510088", "NCT06868602",                       # clean part (14 units)
                          "NCT00672685", "NCT04018092", "NCT02977819", "NCT00935493", "NCT01365104")   # orientation (30)


def texts() -> list[dict]:
    return [json.loads(x) for st in (1, 2, 3) for x in (CAL / f"texts_{st}.jsonl").read_text().splitlines() if x.strip()]


def run() -> None:
    from hyparena.card.normalizer import normalize
    from hyparena.card.pipeline import _client
    client, _ = _client("configs/v3-flash.yaml", False, 120)
    done = json.loads(OUT.read_text()) if OUT.exists() else {}
    for t in texts():
        if t["id"] in done:
            continue
        card, problems = normalize(client, "google", t["text"], "H-0001", version="v8")
        done[t["id"]] = {"card": card.model_dump(by_alias=True) if card else None, "problems": problems}
        OUT.write_text(json.dumps(done, ensure_ascii=False, indent=1))
        print(json.dumps({"id": t["id"], "claims": len(card.claims) if card else None}), flush=True)


def measures(cards: dict, stated=MECHANISM_STATED) -> dict:
    """unparsed: no card, or the outcome claim still 'other' (admission flag unmapped_relation); mechanism: a link before
    the effect (delivery, engagement, pathway) or an effect link the text says leads to the outcome, i.e. any of these with
    a subject other than the intervention; parallel_as_chain: two or more effect links whose subject is the intervention."""
    from hyparena.card.models import HypothesisCard
    from hyparena.card.rules import admit
    out = {"cards": len(cards), "unparsed": [], "mechanism": [], "parallel_as_chain": []}
    for u, c in cards.items():
        if c is None:
            out["unparsed"].append(u)
            continue
        card = HypothesisCard.model_validate(c)
        if "unmapped_relation" in admit(card).flags:
            out["unparsed"].append(u)
        inter = {i.label.lower() for i in card.pico.intervention}
        links = [x for x in card.claims if x.link]
        if any(x.link in MECH_LINKS or (x.link == "effect" and x.subject.label.lower() not in inter) for x in links):
            out["mechanism"].append(u)
        if sum(1 for x in links if x.link == "effect" and x.subject.label.lower() in inter) >= 2:
            out["parallel_as_chain"].append(u)
    stated = set(stated)
    out["mechanism_recall"] = f"{len(stated & set(out['mechanism']))} of {len(stated)}"
    out["mechanism_unstated"] = sorted(set(out["mechanism"]) - stated)
    return {k: (sorted(v) if isinstance(v, list) else v) for k, v in out.items()}


def score() -> dict:
    v7 = json.loads((CAL / "cards_v3.json").read_text())
    res = {"v7": measures(v7)}
    if OUT.exists():
        res["v8"] = measures({k: v["card"] for k, v in json.loads(OUT.read_text()).items()})
    return res


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["run", "score"])
    a = ap.parse_args()
    if a.cmd == "run":
        if os.environ.get("ALLOW_PAID") != "1":
            raise SystemExit("paid: set ALLOW_PAID=1")
        run()
    else:
        print(json.dumps(score(), indent=1))


if __name__ == "__main__":
    main()

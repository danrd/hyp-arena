"""Card task for an outside strong model (Hydrogen): the 22 texts where normalize_card/v15 on the working model made
substantive errors (specs/benchmark-card-2026-11-12.yaml, full_run_v15_2026_11_14.weak_texts). Free, no model call.

    python -m scripts.hydrogen_card_pack build   # longevity-kg/reviews/hydrogen-2026-11-14/card_task.json, card_key.json
    python -m scripts.hydrogen_card_pack score   # after card_answer.json: the same code steps as our pipeline, then the
                                                 # card benchmark v2 measures against the gold, beside the working model

The outside model gets the same instructions as our normaliser (normalize_card/v15, rendered with the closed lists), for
every text at once, and no feedback rounds (our pipeline sends code checks back up to three times and unites two parses).
Its cards then go through the code steps of our pipeline (v15_prepare, primary_from_registry, roles, code fields), so only
the model's own reading differs. The gold is never sent.
"""
from __future__ import annotations

import json
import re
import sys
import typing
from pathlib import Path

HA = Path(__file__).resolve().parents[1]
KG = HA.parent / "longevity-kg"
SRC = KG / "reviews" / "argon-2026-11-13"
OUT = KG / "reviews" / "hydrogen-2026-11-14"
WEAK = "N06 N08 N12 N14 N15 N20 N22 N25 N27 N28 N29 N30 P06 P20 P22 P30 P38 P43 P45 P52 P53 P55".split()

HEAD = """You are parsing research hypotheses on ageing into structured cards. This is a benchmark: answer every item yourself,
from the text only. The instructions below are the ones our parser gets for ONE text; apply them to each item separately.
Take your time on the chain: what the hypothesis promises as its result, what its main factor is, which statements are
steps from the main factor and which are premises about the problem.

"""
TAIL = """

Answer with one JSON object, nothing else:
{"task": "card_v15", "items": [{"id": "W01", "card": { ...the JSON object described above for this text... }}]}
"""


def _instructions() -> str:
    import jinja2
    from hyparena.card.models import Hallmark, Relation
    tmpl = (HA / "hyparena" / "prompts" / "normalize_card" / "v15.j2").read_text()
    tmpl = re.sub(r"Hypothesis text:\n<<<TEXT\n\{\{ text \}\}\nTEXT>>>\n", "Hypothesis text: the \"text\" of each item below.\n", tmpl)
    body = jinja2.Template(tmpl).render(text="", relations=", ".join(typing.get_args(Relation)),
                                        hallmarks=", ".join(typing.get_args(Hallmark)), hint="", history_text="")
    body = body.replace("Reply with a single JSON object and nothing else, with these keys:", "Each item's card is a JSON object with these keys:")
    return HEAD + body.strip() + TAIL


def build() -> dict:
    texts = {i["id"]: i["text"] for i in json.loads((SRC / "pack_19_task.json").read_text())["items"]}
    texts.update({i["id"]: i["text"] for p in "ab" for i in json.loads((SRC / f"pack_20{p}_task.json").read_text())["items"]})
    items, key = [], {}
    for i, k in enumerate(WEAK, 1):
        wid = f"W{i:02d}"
        items.append({"id": wid, "text": texts[k]})
        key[wid] = k
    OUT.mkdir(parents=True, exist_ok=True)
    f = OUT / "card_task.json"
    f.write_text(json.dumps({"task": "card_v15", "written_on": "2026-11-14", "instructions": _instructions(), "items": items},
                            indent=1, ensure_ascii=False) + "\n")
    (OUT / "card_key.json").write_text(json.dumps(key, indent=1) + "\n")
    return {"texts": len(items), "kb": round(f.stat().st_size / 1024)}


def score() -> dict:
    from hyparena.card.normalizer import _problems, registry_defaults, v13_code_fields
    from scripts import bench_card_v2 as bv
    key = json.loads((OUT / "card_key.json").read_text())
    texts = {i["id"]: i["text"] for i in json.loads((OUT / "card_task.json").read_text())["items"]}
    ans = {i["id"]: i.get("card") for i in json.loads((OUT / "card_answer.json").read_text())["items"]}
    cards, failed = {}, []
    for wid, k in key.items():
        raw = ans.get(wid)
        card, problems = _problems(raw, texts[wid], k, core=True, v15=True) if isinstance(raw, dict) else (None, ["no card"])
        if card is not None:
            registry_defaults(card, texts[wid])
            v13_code_fields(card, texts[wid])
        else:
            failed.append(wid)
        cards[k] = {"card": card.model_dump(by_alias=True) if card else {"claims": [], "pico": {"population": {}}, "main_factor": {}},
                    "problems": problems}
    g = bv.gold()
    sub = {k: g[k] for k in key.values()}
    flash = json.loads((bv.DIR / "bench_card_v2_ours_v15.json").read_text())
    out = {"failed": failed, "strong": bv.score_system(cards, sub, True), "working_model": bv.score_system(flash, sub, True),
           "problems_left": sum(bool(v["problems"]) for v in cards.values())}
    (OUT / "card_cards.json").write_text(json.dumps(cards, indent=1, ensure_ascii=False, default=str) + "\n")
    (OUT / "card_score.json").write_text(json.dumps(out, indent=1) + "\n")
    return out


if __name__ == "__main__":
    print(json.dumps({"build": build, "score": score}[sys.argv[1] if len(sys.argv) > 1 else "build"](), indent=1, ensure_ascii=False))

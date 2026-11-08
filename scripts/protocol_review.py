"""Protocol review of each calibration trial by two model families (Argon's layers 1-2, user decision 2026-11-08): endpoint
signal-to-noise, add-on ceiling, time window, power realism, population enrichment, delivery, room for bias. A factor counts
only when the two families agree (else unknown). Paid, about 148 calls (~0.2 USD).

    ALLOW_PAID=1 python -m scripts.protocol_review     # -> calibration/protocol_review.json (+ _summary.json)
"""
from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor

from hyparena.backtest import tied_auc
from hyparena.card.llm import ask
from scripts.ceiling import CAL
from scripts.llm_consensus import CONFIG, FAMILIES, units

LEVELS = {"endpoint_snr": ("low", "medium", "high"), "add_on_ceiling": ("yes", "unclear", "no"),
          "time_window": ("short", "unclear", "adequate"), "power_realism": ("underpowered", "unclear", "adequate"),
          "population_enrichment": ("heterogeneous", "unclear", "enriched"), "delivery": ("doubtful", "unclear", "likely"),
          "bias_room": ("low", "some", "high")}      # ordered so that a higher index = more favourable to a positive result
ALLOWED = {**{k: set(v) for k, v in LEVELS.items()}, "delivery": {"doubtful", "unclear", "likely", "not_applicable"}}


def problems(v: dict) -> list[str]:
    out = []
    for k, allowed in ALLOWED.items():
        lv = ((v or {}).get(k) or {}).get("level")
        if lv not in allowed:
            out.append(f'"{k}.level" must be one of {sorted(allowed)}')
    return out


def score(v: dict, k: str):
    lv = v[k]["level"]
    if lv == "not_applicable":
        return None
    return LEVELS[k].index(lv)


def main() -> dict:
    from hyparena.card.pipeline import _client
    out_f = CAL / "protocol_review.json"
    done = json.loads(out_f.read_text()) if out_f.exists() else {}
    us = units()
    client, _ = _client(CONFIG, False, len(us) * len(FAMILIES) * 2 + 10)

    def one(job):
        u, fam = job
        key = f"{u['id']}|{fam}"
        if key in done:
            return key, done[key]
        v, got = ask(client, role="protocol_review", family=fam, template="protocol_review", version="v1",
                     variables={"text": u["text"], "as_of": u["as_of"]}, validate=problems, rounds=2)
        return key, (v if v and not problems(v) else None)
    with ThreadPoolExecutor(4) as ex:
        for key, v in ex.map(one, [(u, f) for u in us for f in FAMILIES]):
            done[key] = v
    out_f.write_text(json.dumps(done, indent=1, ensure_ascii=False) + "\n")
    rows = []
    for u in us:
        vs = [done.get(f"{u['id']}|{f}") for f in FAMILIES]
        if any(v is None for v in vs):
            continue
        row = {"id": u["id"], "label": u["label"]}
        for k in LEVELS:
            a, b = (score(v, k) for v in vs)
            row[k] = a if a == b else None
            row[k + "_mean"] = None if a is None or b is None else (a + b) / 2
        favourable = [row[k + "_mean"] for k in LEVELS if row[k + "_mean"] is not None]
        row["sum"] = sum(favourable) / len(favourable) if favourable else None
        rows.append(row)

    def auc(key):
        pts = [(r[key], r["label"]) for r in rows if r.get(key) is not None]
        pos, neg = [(v, 0) for v, l in pts if l == 1], [(v, 0) for v, l in pts if l == 0]
        return (round(tied_auc(pos, neg), 3), len(pts)) if pos and neg else None
    agree = {k: round(sum(1 for r in rows if r[k] is not None) / len(rows), 3) for k in LEVELS}
    summary = {"n": len(rows), "agreement": agree, "auc_agreed": {k: auc(k) for k in LEVELS},
               "auc_mean_of_two": {k: auc(k + "_mean") for k in LEVELS}, "auc_sum": auc("sum")}
    (CAL / "protocol_review_summary.json").write_text(json.dumps({"summary": summary, "rows": rows}, indent=1, ensure_ascii=False) + "\n")
    return summary


if __name__ == "__main__":
    if os.environ.get("ALLOW_PAID") != "1":
        raise SystemExit("paid: set ALLOW_PAID=1")
    print(json.dumps(main(), indent=1, ensure_ascii=False))

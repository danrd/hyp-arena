"""Extensions of the effect-phrase parser as variants against the method's references
(specs/scoring/effect-phrase-2026-11-15.yaml); free, no model call.

    python -m scripts.scoring.effect_variants        # -> longevity-kg reviews/argon-2026-11-15/effect_variants.json

The references are those of scripts/scoring/weight_variants.py (R2, R3, pack 23, the AUC of the evidence balance on the 30
trials of pack 18 with the working reader and with reader v16), plus "moved": the records for whose effect factor rises
from 1/2 to 1 under the variant (30 trials, working reader). "current" is the parser before E1 (the interval forms) was
adopted on 2026-11-15; the working code is the row "E1 interval".
"""
from __future__ import annotations

import json
import math
from contextlib import contextmanager

from hyparena.reading import effect_class as ec
from hyparena.scoring import rules_v32 as r32
from scripts.common.v34_check import CAL
from scripts.scoring import weight_variants as wv

OUT = wv.OUT
VARIANTS = {"current": (), "E1 interval": ("interval",), "E2 means": ("means",), "E3 two values": ("two_values",),
            "E4 p value": ("p_value",), "E all": ("interval", "means", "two_values", "p_value")}


@contextmanager
def extra(names):
    saved = ec.EXTRA
    try:
        ec.EXTRA = frozenset(names)
        yield
    finally:
        ec.EXTRA = saved


def _lifted(phrase: str, n, comparison: str) -> bool:
    """A phrase the current parser leaves below medium that the switched-on extensions read as at least medium."""
    if ec.from_phrase(phrase) != "unclear" or ec.d_from_ci(phrase, n, comparison) is not None:
        return False
    d = ec.d_extra(phrase, n, comparison)
    if d is None:
        if ec.class_two_values(phrase) in ("medium", "large"):
            return True
        d = ec.d_from_p(phrase, n, comparison)
    return d is not None and d >= 0.5


def pack23() -> float:
    """Concordance with Argon's order of pack 23; the effect factor of a record for is recomputed where an extension lifts it
    (the key keeps no effect class: a null finding for is not told apart, there are few)."""
    kd = json.loads((OUT / "pack_23_key.json").read_text())
    recs, ans, task = kd["records"], {}, {}
    for i in (1, 2, 3):
        ans.update({p["id"]: p for p in json.loads((OUT / f"pack_23_{i}_answer.json").read_text())["pairs"]})
        task.update({p["id"]: p for p in json.loads((OUT / f"pack_23_{i}_task.json").read_text())["pairs"]})

    def w(rid, factors):
        r, f = recs[rid], dict(factors)
        if r["design"] == "meta_analysis" and not r.get("certainty"):
            f["design"] = f["design"] / 0.75 * wv.rk.NOT_REPORTED            # the key was built at 0.75
        if abs(f["design"] - 2 / 3) < 1e-6 and r["design"] == "review":     # the key was built at 2/3
            f["design"] = wv.lv.PRECLINICAL_REVIEW
        if r.get("context") == "class":
            f["context"] = r32.CLASS_WEIGHT
        comparison = "between_groups" if f["comparison"] == 1.0 else "within_group"
        if r["side"] == "for" and f["effect"] < 1 and _lifted(r.get("effect_reported") or "", r.get("n_total"), comparison):
            f["effect"] = 1.0
        return math.prod(f.values())
    ok = []
    for p in kd["pairs"]:
        if p["swapped"]:
            continue
        t = task[p["id"]]
        wa, wb = w(t["A"], p["factors"][0]), w(t["B"], p["factors"][1])
        d = math.log(wa / wb) if wa > 0 and wb > 0 else 0
        o = 0 if abs(d) < 0.1 else (1 if d > 0 else -1)
        a = {"A": 1, "B": -1, "equal": 0}[ans[p["id"]]["stronger"]]
        if a and o:
            ok.append(a == o)
    return round(sum(ok) / len(ok), 3)


def full_effect() -> set[tuple]:
    """(trial, claim, record) of the records for with the full effect factor, 30 trials, working reader."""
    from hyparena.card.models import EvidenceRecord
    out = set()
    for h, r in json.loads((CAL / "run_5_n15x.json").read_text()).items():
        for cv in (r["items"][0].get("verification") or {}).get("claims", []):
            for e in cv.get("evidence", []):
                if r32.effect_weight(EvidenceRecord.model_validate(e), False) >= r32.EFFECT_FULL_FROM - 1e-9:
                    out.add((h, cv["id"], e["record_id"]))
    return out


def main() -> dict:
    from hyparena.scoring import rules_v3 as r3
    from hyparena.tools import compounds as cp
    from scripts.reading.reader_replay import balance_auc
    from scripts.scoring.empty_slots import r3_auc
    r3.established_by_approval = lambda claim, card: False      # ChEMBL is not reachable here; the same in every variant
    cp._get = lambda url: None
    refs = wv.r2_refs()
    base_full = full_effect()
    out = {}
    for name, names in VARIANTS.items():
        with extra(names):
            out[name] = {"R2": wv.r2_auc(refs), "R3": r3_auc(), "pack23": pack23(),
                         "auc30_v17": balance_auc("n15x")["auc"], "auc30_v16": balance_auc("n14x")["auc"],
                         "moved": len(full_effect() - base_full)}
        print(name, out[name], flush=True)
    base = out["current"]
    for r in out.values():
        r["worse_by_more_than_0.03"] = [k for k in ("R2", "R3", "pack23", "auc30_v17", "auc30_v16")
                                        if r[k] is not None and base[k] - r[k] > 0.03]
    (OUT / "effect_variants.json").write_text(json.dumps(out, indent=1) + "\n")
    return out


if __name__ == "__main__":
    main()

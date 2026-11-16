"""A fixed checklist of methodological threats per system in informativeness I, on the saved runs
(specs/alternatives/threat-checklist-2026-11-16.yaml). Free, no model call: the methodological alternatives the proposer
wrote are dropped by their kind words, the threats of the experiment's system are judged by code from the design, and I
is recomputed beside the saved I; the admission rule of the indicators decides.

    python -m scripts.alternatives.threat_checklist      # -> longevity-kg reviews/argon-2026-11-14/threat_checklist.json
"""
from __future__ import annotations

import json
import tempfile
from collections import Counter
from pathlib import Path

from hyparena.card.models import ClaimVerification, HypothesisCard
from hyparena.card.normalizer import registry_design
from hyparena.novelty import novelty_v34 as nv
from hyparena.scoring import rules_v32, v3_extra
from scripts.alternatives.design_rule import HS, KG, P22, designs60, kind_of, verdict as human_verdict

OUT = P22 / "threat_checklist.json"
CAL, PROS = HS / "calibration", HS / "prospective"
A_CHECKLIST = 0.5
VALUE = {"eliminated": 1.0, "weakened": 0.5, "unchanged": 0.0}
THREATS = {
    "human": ("practice", "regression", "assessor", "expectation", "attention", "selection", "cointervention", "multiplicity"),
    "animal": ("allocation", "assessor", "attrition", "handling", "housing", "sex_strain_age", "multiplicity"),
    "cells": ("batch", "off_target", "vehicle", "culture_artefact", "line_identity", "multiplicity"),
    "data_analysis": ("confounding", "reverse_causation", "selection", "measurement", "multiplicity"),
}
SYSTEM = {"human": "human", "mouse": "animal", "rat": "animal", "worm": "animal", "fly": "animal", "yeast": "cells",
          "in_vitro": "cells", "data_analysis": "data_analysis"}
N_ORDER = nv.LEVELS                 # unknown is left out (drawn over its range)
W_ORDER = ("local", "organ", "hallmark")
D_ORDER = v3_extra.DESIGN_LADDER
E_ORDER = ("biomarker", "patient_reported", "function", "clinical_event")


def design_fields(card: HypothesisCard, reg: dict) -> dict:
    """The registry design fields when there are some, else the card's stated experiment (masking unknown = not masked)."""
    if reg.get("allocation"):
        return reg
    e = card.decisive_experiment
    ctrl = str(e.control or "unknown") not in ("unknown", "none", "")
    dummy = {"placebo": "placebo comparator", "sham": "sham comparator", "active": "active comparator"}.get(str(e.control), "other")
    return {"allocation": "randomized" if e.design == "rct" else "non-randomized" if ctrl else "na",
            "model": "parallel" if ctrl else "single group", "masked": [],
            "arms": [{"type": "experimental"}, {"type": dummy}] if ctrl else [{"type": "experimental"}]}


def checklist(card: HypothesisCard, reg: dict) -> dict:
    system = SYSTEM.get(str(card.decisive_experiment.system))
    if system is None:
        return {"system": None, "share": None, "threats": {}}
    if system == "human":
        f = design_fields(card, reg)
        v = {t: human_verdict(t, f) for t in THREATS[system]}
    else:
        v = {t: "unchanged" for t in THREATS[system]}
    return {"system": system, "share": round(sum(VALUE[x] for x in v.values()) / len(v), 4), "threats": v}


def substantive(card: HypothesisCard) -> HypothesisCard:
    keep = [a for a in card.proposed_alternatives
            if not kind_of(f"{a.subject.label} {a.relation} {a.object.label}. {getattr(a, 'rationale', '') or ''}")]
    return card.model_copy(update={"proposed_alternatives": keep})


def endpoint(f: Path, h: str):
    d = json.loads(f.read_text()) if f.exists() else {}
    v = {d.get(f"{h}|{fam}", {}).get("clean", {}).get("endpoint") for fam in ("google", "deepseek")}
    return v.pop() if len(v) == 1 and None not in v and "not_stated" not in v else None


def designs_calibration(units: list[dict]) -> dict:
    f = CAL / "design_fields.json"
    if f.exists():
        return json.loads(f.read_text())
    from scripts.whole_system.benchmark_run import build_texts
    with tempfile.TemporaryDirectory() as d:
        texts = build_texts([{k: u[k] for k in ("id", "source", "written_on")} for u in units], Path(d) / "t.jsonl")
    out = {t["id"]: registry_design(t["text"]) for t in texts}
    f.write_text(json.dumps(out, indent=1) + "\n")
    return out


def row(h: str, it: dict, as_of: str, reg: dict, est: Path) -> dict:
    from hyparena.alternatives import alternatives_d
    card = alternatives_d.apply(h, HypothesisCard.model_validate(it["card"]))
    cvs = [ClaimVerification.model_validate(c) for c in it["verification"]["claims"]]
    alts = {a: ClaimVerification.model_validate(v) for a, v in (it.get("v3_alternatives") or {}).items()}
    e = rules_v32.evaluate(card, cvs, alts, v36=True)
    sub = substantive(card)
    es = rules_v32.evaluate(sub, cvs, alts, v36=True)
    ck = checklist(card, reg)
    part = A_CHECKLIST * ck["share"] / 1.5 if ck["share"] is not None else 0.0
    ext = v3_extra.extras(card, cvs, it["v3"], as_of)
    return {"id": h, "gate": e.gate, "I_before": e.I, "I_substantive": es.I, "I_after": round(min(1.0, es.I + part), 4),
            "I_checklist_part": round(part, 4), "headroom_after": round(min(1.0, es.headroom_I + A_CHECKLIST / 1.5), 4),
            "alternatives": len(card.proposed_alternatives), "methodological_dropped": len(card.proposed_alternatives) - len(sub.proposed_alternatives),
            "system": ck["system"], "share": ck["share"], "threats": ck["threats"], "registry_fields": bool(reg.get("allocation")),
            "chain_state": e.chain_state, "best_design_outcome": ext["best_design_outcome"], "feasibility": ext["feasibility"],
            "W": e.scope, "N": nv.novelty(card, cvs, e), "endpoint_clinical": endpoint(est, h)}


def rows() -> dict:
    out = {"calibration": [], "prospective": []}
    units = [u for s in range(1, 6) for u in json.loads((CAL / f"units_{s}.json").read_text())]
    regs = designs_calibration(units)
    by = {u["id"]: u for u in units}
    for s in range(1, 6):
        for h, r in json.loads((CAL / f"run_{s}_v10.json").read_text()).items():
            it = r["items"][0]
            if it.get("card") and it.get("verification") and "v3" in it:
                as_of = r["meta"].get("as_of") or by.get(h, {}).get("written_on") or ""
                out["calibration"].append(row(h, it, as_of, regs.get(h) or {}, CAL / "estimand_v1.json"))
    regs = designs60()
    for h, r in json.loads((PROS / "run_60.json").read_text()).items():
        it = r["items"][0]
        if it.get("card") and it.get("verification") and "v3" in it:
            out["prospective"].append(row(h, it, r["meta"].get("as_of") or "", regs.get(h) or {}, PROS / "estimand_60.json"))
    return out


def _spearman(x: list, y: list):
    from scipy.stats import spearmanr
    pairs = [(a, b) for a, b in zip(x, y) if a is not None and b is not None]
    if len(pairs) < 5 or len({a for a, _ in pairs}) < 2 or len({b for _, b in pairs}) < 2:
        return None
    return round(float(spearmanr(*zip(*pairs))[0]), 3)


def _ord(v, order):
    return order.index(v) if v in order else None


def _distribution(xs: list[float]) -> dict:
    s = sorted(xs)
    q = lambda p: s[min(len(s) - 1, int(p * len(s)))]
    common = Counter(round(x, 2) for x in xs).most_common(1)[0]
    return {"n": len(xs), "zeros": sum(1 for x in xs if x == 0), "q25": q(0.25), "median": q(0.5), "q75": q(0.75),
            "max": s[-1], "distinct": len({round(x, 2) for x in xs}), "commonest": common[0], "commonest_share": round(common[1] / len(xs), 3)}


def summary(rs: list[dict]) -> dict:
    after = [r["I_after"] for r in rs]
    red = {k: _spearman(after, [f(r) for r in rs]) for k, f in {
        "chain_state": lambda r: r["chain_state"], "best_design_outcome": lambda r: _ord(r["best_design_outcome"], D_ORDER),
        "endpoint_clinical": lambda r: _ord(r["endpoint_clinical"], E_ORDER), "feasibility": lambda r: r["feasibility"],
        "W": lambda r: _ord(r["W"], W_ORDER), "N": lambda r: _ord(r["N"], N_ORDER)}.items()}
    d = _distribution(after)
    passes = d["distinct"] >= 3 and d["commonest_share"] <= 0.7 and all(v is None or abs(v) < 0.7 for v in red.values())
    tot = sum(r["I_after"] for r in rs)
    return {"before": _distribution([r["I_before"] for r in rs]), "after": d, "redundancy_spearman": red,
            "share_of_I_from_checklist": round(sum(r["I_checklist_part"] for r in rs) / tot, 3) if tot else None,
            "spearman_before_after": _spearman([r["I_before"] for r in rs], after),
            "systems": dict(Counter(r["system"] for r in rs)), "with_registry_fields": sum(r["registry_fields"] for r in rs),
            "methodological_dropped": sum(r["methodological_dropped"] for r in rs), "alternatives": sum(r["alternatives"] for r in rs),
            "checklist_share": dict(sorted(Counter(r["share"] for r in rs).items(), key=lambda x: (x[0] is None, x[0] or 0))),
            "passes_admission": passes}


def main(from_saved: bool = False) -> dict:
    rs = json.loads(OUT.read_text())["rows"] if from_saved else rows()
    res = {"spec": "specs/alternatives/threat-checklist-2026-11-16.yaml", "a_checklist": A_CHECKLIST,
           **{k: summary(v) for k, v in rs.items()}, "rows": rs}
    res["passes"] = all(res[k]["passes_admission"] for k in ("calibration", "prospective"))
    OUT.write_text(json.dumps(res, indent=1, ensure_ascii=False) + "\n")
    return {k: v for k, v in res.items() if k != "rows"}


if __name__ == "__main__":
    import sys
    print(json.dumps(main(from_saved="--summary" in sys.argv), indent=1, ensure_ascii=False))

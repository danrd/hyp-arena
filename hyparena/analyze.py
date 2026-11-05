"""Analysis report of a hypothesis under method v3: why it got its scores and what would raise them.

    python -m hyparena.analyze RUN.json [--unit ID] [--variant v3|v3.1] [--out DIR]

RUN.json is a saved v3 result (a pipeline run, or a calibration run file {unit: run}). The report is built by code from the
card, the verification records and the v3 rules, with no model call, so it is free and reproducible; its sections follow the
template of docs/method-v3-manual.md (section 9), so that a report a model writes from the manual can be compared with it.
Reports on private hypotheses belong in a private repository (default: $KG_DIR/hypothesis_sources/analysis), never in this one.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Optional

from hyparena.card import rules_v3 as r3
from hyparena.card import v3_levels as lv
from hyparena.card.models import ClaimVerification, HypothesisCard

LIMITATIONS = [
    "The verifier keeps about 60% of the relevant papers (precision about 1.0; extraction-gold-v3b/v8/v9): links supported "
    "mostly by interventions of the same kind are under-supported, so P is biased down for programmes and behavioural "
    "interventions.",
    "Abstracts only, unless a row says full_text: per-dose, per-sex and per-statistic results in the full text are missed; "
    "unknown sample size takes the lowest precision band.",
    "Literature is cut at the date T; a later paper can change any link (the living arena re-scores).",
    "Alternatives are proposed by a model from the retrieved literature, not yet by the knowledge graph.",
    "P is the only axis checked against trial outcomes; W, I and V are not predictions of a trial's result.",
]

ACTIONS = {
    "build_mechanism": "Name the mechanism: write the chain from the intervention to the outcome (delivery, engagement, "
                       "pathway, effect, outcome); without it only the outcome link is scored.",
    "name_supported_alternatives": "Name competing explanations that have support in the literature and say what the "
                                   "experiment does to each of them; unsupported alternatives weigh nothing (I stays 1/3).",
    "improve_experiment": "Strengthen the stated experiment so that it cuts off the supported alternatives it now leaves "
                          "standing (arm, control or measure that separates them): see the headroom.",
    "find_primary_report": "A review restates a trial: find the trial's own paper (design, n, effect decide the weight, and "
                           "may decide the gate).",
    "contested_link": "A link has records for and against of comparable weight: the decisive experiment should target it, "
                      "or the hypothesis should say why the records against do not apply.",
    "retracted_source_dropped": "A retracted paper was found among the records and given no weight; check that the argument "
                                "does not rest on it.",
}


def _claim_text(c) -> str:
    return f"{c.subject.label} — {c.relation} — {c.object.label}"


def _records(cv: Optional[ClaimVerification], claim, variant: str, top: int = 3) -> list[dict]:
    if cv is None:
        return []
    out = []
    for against, recs in ((False, cv.evidence), (True, cv.counterevidence)):
        for r in recs:
            w = r3.record_weight(r, claim, against, variant)
            if w <= 0:
                continue
            out.append({"pmid": r.record_id.replace("PMID:", ""), "side": "against" if against else "for", "weight": round(w, 3),
                        "design": r3.record_design(r), "n": r.n_total, "comparison": r.comparison,
                        "effect": r.effect_class, "effect_reported": r.effect_reported, "context": r3.context_level(r),
                        "quote": r.quote[:240]})
    return sorted(out, key=lambda x: -x["weight"])[:top]


def build(card: HypothesisCard, ver_claims: list[ClaimVerification], alts: Optional[dict] = None, variant: str = "v3",
          unit: str = "", meta: Optional[dict] = None, pool: Optional[dict[str, float]] = None) -> dict:
    """The report as a dict (the JSON form); `pool` {unit: V} places the hypothesis among others."""
    res = r3.evaluate(card, ver_claims, alts or {}, variant=variant)
    by_id = {cv.id: cv for cv in ver_claims}
    links = r3.chain(card)
    lw = lambda level: r3._lw(level, variant)
    chain_rows = []
    for c in links:
        level = res.links.get(c.id, "unverified")
        F, A = res.weights.get(c.id, [0.0, 0.0])
        chain_rows.append({"id": c.id, "link": c.link or c.role, "claim": _claim_text(c), "level": level, "S": round(lw(level), 3),
                           "F": F, "A": A, "hallmark": c.object.hallmark or c.subject.hallmark or "",
                           "records": _records(by_id.get(c.id), c, variant)})
    why = []
    if res.gate == "filtered":
        why.append(f"Filtered by the gate: {res.gate_reason}. V is 0 whatever the other links.")
    weakest = next((r for r in chain_rows if r["id"] == res.weakest), None)
    if weakest:
        why.append(f"P = {res.P} is the product over the chain; the weakest link is {weakest['id']} ({weakest['link']}, "
                   f"{weakest['level']}, S = {weakest['S']}): F = {weakest['F']} for, A = {weakest['A']} against.")
    basis = [r["id"] for r in chain_rows if r["level"] in ("weak", "moderate", "strong")]
    why.append(f"W = {res.W} (scope {res.scope}), from the supported links {', '.join(basis) or 'none'}; a scope that is only "
               "claimed, not supported, counts as local.")
    alt_rows = [{"id": k, **v} for k, v in res.alternatives.items()]
    supported = [a for a in alt_rows if a["a"] > 0]
    why.append(f"I = {res.I}: {len(supported)} of {len(alt_rows)} proposed alternatives have support; the stated experiment "
               f"cuts off {sum(1 for a in supported if a['d'] == 1)} and weakens {sum(1 for a in supported if a['d'] == 0.5)}.")
    improve = []
    if weakest and weakest["level"] in ("refuted", "contested", "unverified", "weak") and res.gate == "pass" and weakest["S"] > 0:
        new_P = res.P / weakest["S"] * lw("moderate")
        new_W = lv.weight("scope", "hallmark") if weakest["hallmark"] else res.W
        preclinical = variant == "v3.1" and weakest["link"] in r3.PRECLINICAL_LINKS
        what = ("two or three between-group animal or cell studies with a stated n and a clear effect" if preclinical else
                "about one between-group trial of 100-299 participants with a medium effect, or several smaller studies")
        improve.append({"action": f"Support link {weakest['id']} to the moderate level ({what})"
                                  + ("; it names a hallmark, so the scope would rise too" if new_W > res.W else ""),
                        "V_if_done": round(new_P * new_W * res.I, 5)})
    if res.headroom_V > res.V:
        improve.append({"action": ACTIONS["improve_experiment"], "V_if_done": res.headroom_V})
    for f in res.flags:
        if f in ACTIONS and f != "improve_experiment":
            improve.append({"action": ACTIONS[f], "V_if_done": None})
        elif f.endswith("_established_by_approval"):
            improve.append({"action": f"Link {f.split('_')[0]} is taken as established by an approved drug's mechanism; "
                                      "cite a pharmacology source if the claim goes beyond the approved action.", "V_if_done": None})
    rank = None
    if pool:
        vals = sorted(pool.values(), reverse=True)
        rank = {"place": 1 + sum(v > res.V for v in vals), "of": len(vals)}
    m = meta or {}
    return {"unit": unit or card.id, "variant": variant, "hypothesis": card.claim_plain,
            "summary": {"V": res.V, "P": res.P, "W": res.W, "I": res.I, "gate": res.gate, "headroom_V": res.headroom_V,
                        "rank": rank},
            "chain": chain_rows, "alternatives": alt_rows, "why": why, "improve": improve, "flags": res.flags,
            "limitations": LIMITATIONS,
            "provenance": {"as_of": m.get("as_of"), "config": m.get("config"), "models": m.get("families") or m.get("models"),
                           "calls": m.get("calls"), "created": m.get("created"), "rules": f"rules_v3 variant {variant}"}}


def markdown(rep: dict) -> str:
    s, out = rep["summary"], []
    out.append(f"# Analysis: {rep['unit']} (method {rep['variant']})\n")
    out.append(f"> {rep['hypothesis']}\n")
    out.append("## 1. Summary\n")
    rank = f"; place {s['rank']['place']} of {s['rank']['of']}" if s.get("rank") else ""
    out.append(f"V = **{s['V']}** (P {s['P']} × W {s['W']} × I {s['I']}); gate: {s['gate']}; headroom V = {s['headroom_V']}{rank}.\n")
    out.append("## 2. Mechanism chain\n")
    out.append("| Link | Type | Claim | Level (S) | For / against | Main records |\n|---|---|---|---|---|---|")
    for r in rep["chain"]:
        recs = "; ".join(f"PMID {x['pmid']} {x['side']} w={x['weight']} ({x['design']}, n={x['n'] or '?'}, {x['effect']})"
                         for x in r["records"]) or "none"
        out.append(f"| {r['id']} | {r['link']} | {r['claim']} | {r['level']} ({r['S']}) | {r['F']} / {r['A']} | {recs} |")
    out.append("\n## 3. Why this score\n")
    out += [f"- {w}" for w in rep["why"]]
    if rep["alternatives"]:
        out.append("\n| Alternative | Support a | Cut off by the experiment d | Level |\n|---|---|---|---|")
        out += [f"| {a['id']} | {a['a']} | {a['d']} | {a['level']} |" for a in rep["alternatives"]]
    out.append("\n## 4. What to improve\n")
    out += [f"- {x['action']}" + (f" (V would be {x['V_if_done']})" if x["V_if_done"] is not None else "") for x in rep["improve"]] \
        or ["- Nothing the rules can point at: the hypothesis is limited by the strength of its links as they are."]
    out.append("\n## 5. Limitations\n")
    out += [f"- {x}" for x in rep["limitations"]]
    out.append("\n## 6. Provenance\n")
    out += [f"- {k}: {v}" for k, v in rep["provenance"].items() if v is not None]
    return "\n".join(out) + "\n"


def from_run(run: dict, variant: str = "v3") -> list[dict]:
    """Reports for every item of a saved run with a v3 result: one pipeline run, or {unit: run} as calibration files."""
    runs = run if "items" not in run else {"": run}
    items = []
    for unit, r in runs.items():
        for it in r.get("items", []):
            if it.get("card") and it.get("verification") and "v3" in it:
                items.append((unit or it.get("id", ""), it, r.get("meta", {})))
    pool = {}
    built = []
    for unit, it, meta in items:
        card = HypothesisCard.model_validate(it["card"])
        claims = [ClaimVerification.model_validate(c) for c in it["verification"]["claims"]]
        alts = {k: ClaimVerification.model_validate(v) for k, v in (it.get("v3_alternatives") or {}).items()}
        built.append((unit, card, claims, alts, meta))
        pool[unit] = r3.evaluate(card, claims, alts, variant=variant).V
    return [build(card, claims, alts, variant, unit, meta, pool) for unit, card, claims, alts, meta in built]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("run")
    ap.add_argument("--unit", default="")
    ap.add_argument("--variant", default="v3", choices=list(r3.VARIANTS))
    ap.add_argument("--out", default=os.path.join(os.environ.get("KG_DIR", "/home/user/longevity-kg"), "hypothesis_sources", "analysis"))
    a = ap.parse_args()
    reps = [r for r in from_run(json.loads(Path(a.run).read_text()), a.variant) if not a.unit or r["unit"] == a.unit]
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    for r in reps:
        stem = f"{r['unit'] or 'hypothesis'}_{a.variant}"
        (out / f"{stem}.json").write_text(json.dumps(r, ensure_ascii=False, indent=1))
        (out / f"{stem}.md").write_text(markdown(r))
        print(out / f"{stem}.md")


if __name__ == "__main__":
    main()

"""Free check (user request 2026-11-09): does a code rule fix the matrix's systematic error, a proposed competitor of the same
kind as a checklist row (natural course, expectation, practice ...) not inheriting that row's "held equal"? Saved v2 answers.

    python -m scripts.test_model_fixcheck      # -> prospective/test_model_{dev,holdout}_v2fix.json, prints kappa
"""
from __future__ import annotations

import json

from scripts.test_model import PROS, compute, score, units

KW = {"k_expect": ("placebo", "expectanc", "expectation", "unblind", "nocebo"),
      "k_attention": ("attention", "contact", "supervision", "social", "nonspecific", "non-specific"),
      "k_course": ("regression to the mean", "natural recovery", "natural course", "spontaneous", "natural fluctuation",
                   "trajectory", "age-related decline"),
      "k_measure": ("practice", "test-retest", "learning effect", "familiarity", "repeated participation", "assessment effect"),
      "k_selection": ("selection", "attrition", "baseline", "confounding by indication", "sicker"),
      "k_cointerv": ("co-intervention", "cointervention", "usual care", "standard care")}


def main() -> dict:
    out = {}
    for part in ("dev", "holdout"):
        res = json.loads((PROS / f"test_model_{part}_v2.json").read_text())
        U = {h: (text, p) for h, text, p in units(part)}
        new = {}
        for h, r in res.items():
            text, (card, cvs, alts) = U[h]
            v = json.loads(json.dumps(r["raw"] or {}))
            rows = {m.get("row"): m for m in v.get("matrix") or [] if isinstance(m, dict)}
            held = list(v.get("held_equal") or [])
            for a in card.proposed_alternatives:
                claim = f"{a.subject.label} {a.relation} {a.object.label}".lower()
                for k, ws in KW.items():
                    if not any(w in claim for w in ws):
                        continue
                    for x in [x for x in held if x.get("row") == k]:
                        held.append({"row": a.id, "comparison": x.get("comparison"), "phrase": x.get("phrase")})
                        if a.id in rows and k in rows:
                            rows[a.id].setdefault("cells", {})[x.get("comparison")] = rows[k]["cells"].get(x.get("comparison"), "0")
            v["held_equal"] = held
            new[h] = {"raw": v, **compute(v, text, [a.id for a in card.proposed_alternatives])}
        (PROS / f"test_model_{part}_v2fix.json").write_text(json.dumps(new) + "\n")
        s = score(part, "v2fix")
        out[part] = {k: s[k] for k in ("kappa_d_matrix_vs_argon", "kappa_d_judge_vs_argon_same_trials", "d_matrix")}
    return out


if __name__ == "__main__":
    print(json.dumps(main(), indent=1))

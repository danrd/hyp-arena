"""The registry design fields (allocation, model, who is masked, arm types) written into the cards of saved runs made before
normaliser v13, which parsed them from the text (hyparena.card.normalizer.design_from_registry). Free, no model call: the
fields come from the cached parse of the registry (calibration: design_fields.json from the texts; prospective:
pack_6_design_fields.json from ClinicalTrials.gov). The registry decides randomisation both ways, as in the normaliser.
Method v3.11 judges methodological threats in humans from these fields; without them masking reads as not stated.

    python -m scripts.data.registry_fields_backfill        # rewrites the saved runs in longevity-kg in place (git keeps the old)
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from scripts.alternatives.design_rule import HS, P6

SOURCES = {HS / "calibration": HS / "calibration" / "design_fields.json",
           HS / "prospective": P6 / "pack_6_design_fields.json"}


def fill(card: dict, reg: dict) -> list[str]:
    e = card.setdefault("decisive_experiment", {})
    done = []
    if reg and not (e.get("registry") or {}).get("allocation"):
        e["registry"] = {**reg, **(e.get("registry") or {})}
        done.append("registry")
    alloc = (e.get("registry") or {}).get("allocation")
    if alloc == "randomized" and e.get("design", "unknown") in ("unknown", "other"):
        e["design"] = "rct"; done.append("design rct")
    elif alloc == "non_randomized" and e.get("design") in ("rct", "cluster_rct"):
        e["design"] = "other"; done.append("design other")
    return done


def main() -> dict:
    out = {}
    for folder, src in SOURCES.items():
        regs = json.loads(src.read_text())
        for f in sorted(folder.glob("run_*.json")):
            res = json.loads(f.read_text())
            if not isinstance(res, dict):
                continue
            c = Counter()
            for h, r in res.items():
                for it in (r.get("items") or []) if isinstance(r, dict) else []:
                    if isinstance(it, dict) and it.get("card") and h in regs:
                        c.update(fill(it["card"], regs[h]))
            if c:
                f.write_text(json.dumps(res, ensure_ascii=False, default=str))    # the compact form the runs were saved in
                out[str(f.relative_to(HS))] = dict(c)
    return out


if __name__ == "__main__":
    print(json.dumps(main(), indent=1, ensure_ascii=False))

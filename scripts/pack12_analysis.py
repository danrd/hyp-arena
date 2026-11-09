"""Analysis of Argon pack 12 (specs/meta-and-nulls-2026-11-09.yaml). Free.

    python -m scripts.pack12_analysis
"""
from __future__ import annotations

import json
from collections import Counter

from scripts.pack12_meta_nulls import DIR
from scripts.v34_check import CAL


def main() -> dict:
    ans = {i["id"]: i for i in json.loads((DIR / "pack_12_answer.json").read_text())["items"]}
    key = json.loads((DIR / "pack_12_key.json").read_text())
    out = {}
    for kind in ("meta_analysis_for", "rct_against"):
        ids = [i for i, k in key.items() if k["kind"] == kind and i in ans]
        read = [i for i in ids if ans[i].get("status") == "read"]
        flag = "abstract_overstates" if kind == "meta_analysis_for" else "abstract_understates"
        yes = [i for i in read if ans[i].get(flag) == "yes"]
        row = {"items": len(ids), "read": len(read), flag: f"{len(yes)}/{len(read)}",
               "kinds": dict(Counter(k for i in yes for k in ans[i].get("kinds") or []).most_common())}
        if kind == "meta_analysis_for":
            row["grade"] = dict(Counter((ans[i].get("pooled") or {}).get("grade") or "missing" for i in read))
            row["risk_of_bias"] = dict(Counter((ans[i].get("pooled") or {}).get("risk_of_bias") or "missing" for i in read))
            row["low_or_very_low"] = sum(1 for i in read if str((ans[i].get("pooled") or {}).get("grade", "")).lower() in ("low", "very low"))
        else:
            row["claim_outcome_primary"] = dict(Counter(str((ans[i].get("trial") or {}).get("claim_outcome_primary")) for i in read))
            row["sample_size_reached"] = dict(Counter(str((ans[i].get("trial") or {}).get("reached")) for i in read))
        row["examples"] = [f"{i} PMID {key[i]['pmid']}: {(ans[i].get('evidence') or '')[:160]}" for i in yes[:6]]
        out[kind] = row
    (CAL / "pack12_analysis.json").write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    return out


if __name__ == "__main__":
    print(json.dumps(main(), indent=1, ensure_ascii=False))

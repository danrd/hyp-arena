"""Analysis of Argon pack 11 (specs/abstract-overstates-2026-11-09.yaml). Free.

    python -m scripts.pack11_analysis
"""
from __future__ import annotations

import json
from collections import Counter

from scripts.pack11_overstates import DIR
from scripts.v34_check import CAL


def main() -> dict:
    ans = {i["id"]: i for i in json.loads((DIR / "pack_11_answer.json").read_text())["items"]}
    key = json.loads((DIR / "pack_11_key.json").read_text())
    out = {}
    for arm in ("targeted", "control"):
        ids = [i for i, k in key.items() if k["arm"] == arm and i in ans]
        read = [i for i in ids if ans[i]["B"].get("status") == "read"]
        over = [i for i in read if ans[i]["abstract_overstates"] == "yes"]
        flip = [i for i in read if ans[i]["A"].get("finding") == "for" and ans[i]["B"].get("finding") in ("against", "none")]
        serious = [i for i in over if set(ans[i]["kinds"]) & {"primary_omitted", "subgroup", "secondary_as_main", "within_group_as_between"}]
        out[arm] = {"papers": len(ids), "full_text_read": len(read), "overstates": f"{len(over)}/{len(read)}",
                    "overstates_serious_kinds": f"{len(serious)}/{len(read)}",
                    "stance_flips_for_to_null_or_against": [f"{i} PMID {key[i]['pmid']}" for i in flip],
                    "kinds": dict(Counter(k for i in over for k in ans[i]["kinds"]).most_common())}
    (CAL / "pack11_analysis.json").write_text(json.dumps(out, indent=1) + "\n")
    return out


if __name__ == "__main__":
    print(json.dumps(main(), indent=1))

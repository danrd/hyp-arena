"""Seed the short id registry (user decision 2026-11-11): the prospective 60 keep H01-H60 (registry id order, as the
agreed report showed them), their saved versions follow their parents, then the 74 calibration trials (registry id order).
Append-only: running it again adds nothing that is already there.

    python -m scripts.short_ids_seed [--dry]
"""
from __future__ import annotations

import argparse
import json

from hyparena import short_ids as si
from hyparena.report_html import EVO_FILES

DATE = "2026-11-11"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()
    hs = si.KG / "hypothesis_sources"
    rows = si.load()
    pro = sorted(u["id"] for u in json.loads((hs / "prospective" / "units_60.json").read_text()))
    new = si.assign(rows, pro, "prospective-60", DATE)
    rows = rows + new
    for mode, fname in EVO_FILES.items():
        f = hs / "prospective" / fname.format(n=60)
        if not f.exists():
            continue
        for parent in sorted(json.loads(f.read_text())["pairs"]):
            if any(r.get("parent") == si.stable_id(parent) and r.get("mode") == mode for r in rows):
                continue
            row = si.assign_version(rows, parent, mode, DATE, "prospective-60")
            rows.append(row)
            new.append(row)
    cal = sorted({u["id"] for i in range(1, 6) for u in json.loads((hs / "calibration" / f"units_{i}.json").read_text())})
    c = si.assign(rows, cal, "calibration-74", DATE)
    new += c
    print(f"{len(new)} new rows; registry {si.REGISTRY}")
    for r in new[:3] + new[-3:]:
        print(" ", r)
    if not a.dry:
        si.append(new)


if __name__ == "__main__":
    main()

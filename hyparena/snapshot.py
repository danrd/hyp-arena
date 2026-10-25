"""Golden snapshot of the ITP-2010 backtest: one row per tested regimen (status of the main claim, place under the
`evidence_first` profile, expectation, P(top-k)), written from the site bundle that `site.export_itp` builds from the
saved runs. No model calls. A change in the snapshot must be recorded in docs/itp_2010_changes_after_first_run.csv
(`tests/test_snapshot.py` compares the two)."""
from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path

SNAPSHOT = Path("tests/fixtures/itp2010_snapshot.csv")
CHANGES = Path("docs/itp_2010_changes_after_first_run.csv")
PROFILE = "evidence_first"
FIELDS = ["id", "compound", "dose", "start", "later_label", "outcome", "main_status", "place", "expected", "p_topk"]


def places(P: dict) -> dict[str, str]:
    """Place ranges of one profile: consecutive hypotheses within the Monte Carlo error of the difference share one."""
    E, S, K, order = P["expected"], P.get("std") or {}, P["K"], P["order"]
    tied = lambda a, b: abs(E[a] - E[b]) < 1.96 * math.sqrt((S.get(a, 0) ** 2 + S.get(b, 0) ** 2) / K)
    out, i = {}, 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and all(tied(m, order[j + 1]) for m in order[i:j + 1]):
            j += 1
        for m in order[i:j + 1]:
            out[m] = str(i + 1) if i == j else f"{i + 1}-{j + 1}"
        i = j + 1
    return out


def rows_from_bundle(bundle: dict) -> list[dict]:
    P = bundle["profiles"][PROFILE]
    place = places(P)
    rows = []
    for h in bundle["hypotheses"]:
        claims = (h.get("verification") or {}).get("claims") or []
        main = next((c["status"] for c in claims if (c.get("claim") or {}).get("role") == "outcome"), "")
        title = h["title"]
        compound, _, rest = title.partition(", ")
        dose, _, start = rest.partition(", ")
        rows.append({"id": h["id"], "compound": compound, "dose": dose, "start": start.replace("старт ", ""),
                     "later_label": h["after"]["label"], "outcome": h["outcome"], "main_status": main,
                     "place": place.get(h["id"], ""),
                     "expected": f"{P['expected'][h['id']]:.3f}" if h["id"] in P["expected"] else "",
                     "p_topk": f"{P['p_topk'][h['id']]:.3f}" if h["id"] in P["p_topk"] else ""})
    return sorted(rows, key=lambda r: r["id"])


def write(rows: list[dict], path: Path = SNAPSHOT) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf8") as f:
        w = csv.DictWriter(f, FIELDS, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def read(path: Path = SNAPSHOT) -> list[dict]:
    with path.open(newline="", encoding="utf8") as f:
        return list(csv.DictReader(f))


def diff(old: list[dict], new: list[dict], tol_e: float = 0.002, tol_p: float = 0.02) -> list[str]:
    """What differs between two snapshots: status, outcome and place exactly, numbers within the Monte Carlo error."""
    a, b, out = {r["id"]: r for r in old}, {r["id"]: r for r in new}, []
    for i in sorted(set(a) | set(b)):
        if i not in a or i not in b:
            out.append(f"{i}: {'added' if i in b else 'removed'}")
            continue
        for k in ("outcome", "main_status", "place", "later_label"):
            if a[i][k] != b[i][k]:
                out.append(f"{i}: {k} {a[i][k]!r} -> {b[i][k]!r}")
        for k, tol in (("expected", tol_e), ("p_topk", tol_p)):
            x, y = a[i][k], b[i][k]
            if (x == "") != (y == "") or (x != "" and abs(float(x) - float(y)) > tol):
                out.append(f"{i}: {k} {x} -> {y}")
    return out


def main() -> None:
    from hyparena.site import export_itp
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dev", default="runs/stage4/itp2010_dev.reapplied.json")
    ap.add_argument("--test", default="runs/stage4/itp2010_test.reapplied.json")
    ap.add_argument("--labels", default="data/backtest/itp_2010-12-31_labels.json")
    ap.add_argument("--check", action="store_true", help="compare with the committed snapshot instead of writing it")
    ap.add_argument("--out", default=str(SNAPSHOT), help="where to write (the exploratory snapshot goes to its own file)")
    a = ap.parse_args()
    rows = rows_from_bundle(export_itp(a.dev, a.test, a.labels))
    if a.check:
        d = diff(read(Path(a.out)), rows)
        print("\n".join(d) or "snapshot unchanged")
        raise SystemExit(1 if d else 0)
    write(rows, Path(a.out))
    print(f"{len(rows)} rows -> {a.out}")


if __name__ == "__main__":
    main()

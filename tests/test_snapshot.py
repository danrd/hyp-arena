"""E1: the golden snapshot of the ITP-2010 backtest. A change of status, outcome or place needs a line in the
list `docs/itp_2010_changes_after_first_run.csv`; the numbers are compared within the Monte Carlo error."""
import csv
from pathlib import Path

import pytest

from hyparena import snapshot

RUNS = [Path(p) for p in ("runs/stage4/itp2010_dev.reapplied.json", "runs/stage4/itp2010_test.reapplied.json")]


def test_snapshot_is_well_formed():
    rows = snapshot.read()
    ids = [r["id"] for r in rows]
    assert len(rows) == 70 and len(set(ids)) == 70
    assert {r["later_label"] for r in rows} <= {"supports", "no_effect", "harmful"}
    ranked = [r for r in rows if r["outcome"] == "ranked"]
    assert all(r["place"] and r["expected"] for r in ranked)
    assert all(not r["place"] for r in rows if r["outcome"] != "ranked")


def test_snapshot_agrees_with_the_changes_list():
    """The list of changes after the first run states the result after the last change; the snapshot must say the same."""
    changes = {r["id"]: r for r in csv.DictReader(open(snapshot.CHANGES, encoding="utf8"))}
    snap = {r["id"]: r for r in snapshot.read()}
    assert set(snap) == set(changes)
    for i, c in changes.items():
        r = snap[i]
        assert r["main_status"] == c["main_status_after"], i
        assert r["outcome"] == c["outcome_after"], i
        assert r["later_label"] == c["later_label"], i
        assert r["place"] == (c["place_after"] if c["place_after"] != "—" else ""), i
        if r["expected"]:
            assert abs(float(r["expected"]) - float(c["expected_after"])) < 0.0015, i


def test_diff_names_every_kind_of_change():
    a = snapshot.read()
    b = [dict(r) for r in a]
    b[0]["main_status"] = "refuted"
    b[1]["place"] = "1"
    b[2]["expected"] = f"{float(b[2]['expected']) + 0.01:.3f}"
    b.pop()
    out = snapshot.diff(a, b)
    assert len(out) == 4 and any("removed" in x for x in out) and any("main_status" in x for x in out)
    assert snapshot.diff(a, a) == []


@pytest.mark.skipif(not all(p.exists() for p in RUNS), reason="the saved runs are not in this checkout (runs/ is not tracked)")
def test_snapshot_matches_the_saved_runs():
    """Recomputed from the saved verifications, no model calls: the pooled ranking at T must equal the snapshot."""
    from hyparena.site import export_itp
    rows = snapshot.rows_from_bundle(export_itp(str(RUNS[0]), str(RUNS[1]), "data/backtest/itp_2010-12-31_labels.json"))
    assert snapshot.diff(snapshot.read(), rows) == []

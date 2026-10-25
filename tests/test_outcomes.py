"""Backtest pools from curated program outcomes and their metrics (offline)."""
import json

from hyparena import outcomes as oc


def test_tests_load_and_resolve_quotes():
    tests = oc.load_tests()
    assert len({t["id"] for t in tests}) == len(tests)
    assert all(t.get("quote") and t["label"] in oc.ORDER for t in tests)
    berb = next(t for t in tests if t["id"] == "citp-2025-berberine")
    assert "berberine" in berb["quote"]


def test_dates_known_only_to_the_year():
    t = {"public_date": "2026-01-01", "date_precision": "year"}
    assert not oc.after(t, "2026-03-31") and not oc.after(t, "2026-01-01")   # the year of T: left out
    assert oc.after(t, "2025-12-31")


def test_repeats_need_their_own_regimen():
    tests = {t["id"]: t for t in oc.load_tests()}
    assert oc.phrasable(tests["itp-2024-cana-16m"])                  # start age stated
    assert not oc.phrasable(tests["itp-2026-astaxanthin-repeat"])    # dose and age not in the abstract
    assert oc.phrasable(tests["citp-2026-meclizine-high"])


def test_text_states_the_claim_not_the_result():
    tests = {t["id"]: t for t in oc.load_tests()}
    t = oc.text(tests["itp-2023-astaxanthin"])
    assert t.startswith("Dietary astaxanthin (at 1840 ppm, started at 12 months)") and "12%" not in t
    assert "Caenorhabditis" in oc.text(tests["citp-2025-berberine"])


def test_build_pool_and_sets(tmp_path, monkeypatch):
    monkeypatch.setattr(oc, "OUT", tmp_path)
    data, labels = oc.build("2024-12-31", clean_after="2025-06-30")
    pool, lab = json.loads(data.read_text()), json.loads(labels.read_text())
    assert len(pool["hypotheses"]) == len(lab) == oc.counts(["2024-12-31"])[0]["tests"]
    assert pool["source"]["as_of"] == "2024-12-31" and "outcome" not in json.dumps(pool["hypotheses"])
    sets = {v["test"]: v["set"] for v in lab.values()}
    assert sets["citp-2025-tamibarotene"] == "historical" and sets["itp-2025-epicatechin"] == "clean"
    assert all(v["split"] in ("dev", "test") for v in lab.values())


def test_effect_size():
    assert oc.effect({"label": "supports", "effect_percent": {"male": 15, "female": -7}}) == 15
    assert oc.effect({"label": "harmful", "effect_percent": {"female": -4}}) == -4
    assert oc.effect({"label": "no_effect"}) == 0.0
    assert oc.effect({"label": "supports"}) is None


def test_cutoff_heuristic_and_eligibility():
    cut = oc.cutoffs()
    assert cut["gemini-3.5-flash"] == "2025-11-19"
    assert oc.eligible("2025-12-31", ["gemini-3.5-flash", "unknown-model"]) == {"gemini-3.5-flash": True,
                                                                                "unknown-model": False}
    assert oc.eligible("2025-06-30", ["gemini-3.5-flash"]) == {"gemini-3.5-flash": False}


def test_metrics():
    labels = {"a": {"outcome": "supports", "effect": 12.0, "set": "clean"},
              "b": {"outcome": "supports", "effect": 5.0, "set": "clean"},
              "c": {"outcome": "no_effect", "effect": 0.0, "set": "clean"},
              "d": {"outcome": "harmful", "effect": -4.0, "set": "historical"}}
    scores = {"a": 0.9, "b": 0.7, "c": 0.5, "d": 0.1}
    pw = {"a": {"b": 0.6, "c": 0.8, "d": 0.9}, "b": {"c": 0.7, "d": 0.8}, "c": {"d": 0.7}}
    m = oc.metrics(labels, scores, pw, k=2)
    assert m["auc"] == 1.0 and m["precision_at_k"] == 1.0 and abs(m["spearman_effect"] - 1.0) < 1e-9
    assert m["calibration"]["pairs"] == 5 and 0 < m["calibration"]["brier"] < 0.25   # a-b: same label, left out
    assert oc.metrics(labels, scores, subset="clean")["n"] == 3


def test_scores_from_a_v2_output():
    res = {"items": [{"id": "H-0001", "outcome": "ranked"}, {"id": "H-0002", "outcome": "filtered"},
                     {"id": "H-0003", "outcome": "known_result"}],
           "ranking": {"evidence_first": {"expected": {"H-0001": 0.4}}}}
    s = oc.scores_v2(res, "evidence_first")
    assert s["imp001"] == 0.4 and s["imp002"] == float("-inf") and s["imp003"] == float("inf")


def test_date_audit_finds_records_after_t(tmp_path, monkeypatch):
    from hyparena import backtest
    res = {"meta": {"as_of": "2010-12-31"}, "items": [{"id": "H-0001", "verification": {
        "claims": [{"id": "c1", "evidence": [{"record_id": "PMID:1"}], "counterevidence": [
            {"record_id": "DrugAge:x", "linked_pmid": "2"}], "refusals": []}],
        "alternatives": [{"id": "alt1", "record_id": "PMID:3"}]}}]}
    path = tmp_path / "r.json"
    path.write_text(json.dumps(res))
    monkeypatch.setattr(backtest, "_pubdates", lambda ids: {"1": "2009-01-01", "2": "2012-03-26", "3": "2010-12-31"})
    got = backtest.audit(str(path))
    assert not got["ok"] and list(got["after_T"]) == ["2"] and got["after_T"]["2"]["where"] == ["H-0001/c1"]


def test_ablate_without_drop_reproduces_the_aggregation(tmp_path):
    import json
    from hyparena.aspid import aggregate, load_profiles
    from hyparena.backtest import ablate
    from hyparena.card import indicators as ind
    vals = {"H-1": {"effect_level": "mammals", "path_to_human": "1", "late_start": 0.3},
            "H-2": {"effect_level": "none", "path_to_human": "1", "late_start": [0.6, 0.7]},
            "H-3": {"effect_level": "none", "path_to_human": "0", "late_start": None}}
    items = [{"id": h, "outcome": "ranked", "indicators": v} for h, v in vals.items()] + [{"id": "H-4", "outcome": "filtered"}]
    f = tmp_path / "v2.json"
    f.write_text(json.dumps({"meta": {"as_of": "2010-12-31", "ids": ["a", "b", "c", "d"]}, "items": items}))
    want = aggregate(vals, ind.INDICATORS, load_profiles()["evidence_first"], K=2000).expected
    got = ablate(str(f), ["none"], K=2000)["hypotheses"]
    assert all(abs(got[k]["combined"] - 2.0 - want[h]) < 1e-9 for k, h in zip("abc", vals))
    assert got["d"]["combined"] < 1.0
    assert ablate(str(f), ["late_start"], K=2000)["hypotheses"]["a"]["combined"] != got["a"]["combined"]


def test_a_run_made_with_three_path_levels_is_still_read_with_them(tmp_path):
    """Runs before 2026-10-25 record path_to_human with the levels 2, 1, 0; the saved levels decide, not the current set."""
    import json
    from hyparena.backtest import ablate
    meta = {"as_of": "2010-12-31", "ids": ["a", "b"],
            "indicators": [{"id": "effect_level", "kind": "ordinal", "levels": list(__import__("hyparena.card.models", fromlist=["RUNGS"]).RUNGS)},
                           {"id": "path_to_human", "kind": "ordinal", "levels": ["2", "1", "0"]}]}
    items = [{"id": "H-1", "outcome": "ranked", "indicators": {"effect_level": "none", "path_to_human": "2"}},
             {"id": "H-2", "outcome": "ranked", "indicators": {"effect_level": "none", "path_to_human": "0"}}]
    f = tmp_path / "v2.json"
    f.write_text(json.dumps({"meta": meta, "items": items}))
    got = ablate(str(f), ["none"], K=2000)["hypotheses"]
    assert got["b"]["combined"] > got["a"]["combined"]              # level 0 (nothing to do first) is better than level 2

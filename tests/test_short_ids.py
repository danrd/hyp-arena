import pytest

from hyparena import short_ids as si


def test_stable_ids_and_leading_zero():
    assert si.stable_id("NCT07726758") == "ctgov:NCT07726758"
    assert si.stable_id("ISRCTN13364395") == "isrctn:ISRCTN13364395"
    assert si.stable_id("bioarena:abc") == "bioarena:abc"
    with pytest.raises(ValueError):
        si.stable_id("XYZ1")
    assert [si.fmt(n) for n in (7, 60, 134, 1001)] == ["H07", "H60", "H134", "H1001"]


def test_numbers_are_global_append_only_and_never_move():
    rows = si.assign([], ["NCT2", "NCT1"], "a", "d")
    assert [(r["id"], r["short"]) for r in rows] == [("ctgov:NCT2", "H01"), ("ctgov:NCT1", "H02")]
    more = si.assign(rows, ["NCT1", "NCT0", "ISRCTN9"], "b", "d")      # NCT1 is kept, the others go after
    assert [(r["id"], r["short"]) for r in more] == [("ctgov:NCT0", "H03"), ("isrctn:ISRCTN9", "H04")]


def test_versions_take_the_parent_id_the_mode_letter_and_a_number_from_the_second():
    rows = si.assign([], ["NCT1"], "a", "d")
    v1 = si.assign_version(rows, "NCT1", "tune", "d")
    v2 = si.assign_version(rows + [v1], "NCT1", "tune", "d")
    v3 = si.assign_version(rows + [v1, v2], "NCT1", "directed", "d")
    assert (v1["short"], v2["short"], v3["short"]) == ("H01д", "H01д2", "H01н")
    assert v2["id"] == "evo:ctgov:NCT1/tune/2"
    with pytest.raises(KeyError):
        si.assign_version(rows, "NCT9", "tune", "d")


def test_duplicates_are_refused():
    rows = [{"id": "ctgov:NCT1", "short": "H01"}, {"id": "ctgov:NCT2", "short": "H01"}]
    with pytest.raises(ValueError):
        si.assign(rows, [], "a", "d")


def test_report_rows_are_mapped_through_the_registry(tmp_path):
    rows = si.assign([], ["NCT1", "NCT2"], "a", "d")
    rows.append(si.assign_version(rows, "NCT2", "tune", "d"))
    p = tmp_path / "r.jsonl"
    si.append(rows, p)
    res = [{"id": "NCT2", "is_evolved": False}, {"id": "NCT2+evo", "is_evolved": True, "parent_id": "NCT2", "evo_mode": "tune"},
           {"id": "NCT3", "is_evolved": False}, {"id": "odd", "is_evolved": False}]
    assert si.for_report(res, si.load(p)) == {"NCT2": "H02", "NCT2+evo": "H02д"}

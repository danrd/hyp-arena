import random

from scripts.diagnostics_calibration import permute, summary


class S:
    def __init__(self, id): self.id = id


def test_permutation_keeps_every_column_and_breaks_the_rows():
    values = {f"h{i}": {"a": i % 2, "b": f"L{i % 3}", "c": None} for i in range(12)}
    out = permute(values, [S("a"), S("b"), S("c")], random.Random(1))
    for k in "abc":
        assert sorted(map(str, (v[k] for v in values.values()))) == sorted(map(str, (v[k] for v in out.values())))
    assert any(values[h] != out[h] for h in values)


def test_summary_reports_median_and_the_5_95_range():
    assert summary([{"x": v} for v in range(1, 22)], lambda r: r["x"]) == "11.00 [2.00; 20.00]"
    assert summary([{"x": None}], lambda r: r["x"]) == "-"

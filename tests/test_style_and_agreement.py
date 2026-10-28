from scripts.style_check import tau, verdict as style_verdict
from scripts.verifier_agreement import kappa, verdict as agree_verdict


def test_style_verdict_passes_only_if_every_pair_is_within_the_repeat_minus_the_tolerance():
    assert style_verdict({"a": 0.8, "b": 0.76}, 0.8)["status"] == "pass"
    assert style_verdict({"a": 0.8, "b": 0.7}, 0.8)["status"] == "fail"
    assert tau([1, 2, 3, 4], [1, 2, 3, 4]) == 1.0


def test_kappa_is_one_for_identical_labels_and_zero_for_chance_agreement():
    a = ["s", "s", "r", "u"] * 5
    assert kappa(a, a) == 1.0
    assert abs(kappa(["a", "b"] * 10, ["a", "a", "b", "b"] * 5)) < 1e-9


def test_agreement_verdict_is_uninformative_without_enough_non_default_statuses():
    st = {f: ["unverified"] * 30 for f in ("deepseek", "google", "zhipu")}
    assert agree_verdict(st)["status"] == "uninformative"
    mix = ["supported"] * 8 + ["refuted"] * 4 + ["unverified"] * 18
    assert agree_verdict({f: mix for f in ("deepseek", "google", "zhipu")})["status"] == "pass"

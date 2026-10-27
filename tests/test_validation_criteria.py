"""The validation criteria file is well formed, its evidence exists, and the rendered table is up to date."""
import re
from pathlib import Path

from scripts import validation_table as vt


def test_every_test_has_the_required_fields_and_valid_values():
    spec = vt.load()
    ids = [t["id"] for t in spec["tests"]]
    assert len(ids) == len(set(ids))
    for t in spec["tests"]:
        assert t["level"] in spec["levels"] and t["status"] in vt.STATUS and t["declared"] in vt.DECLARED and t["kind"] in vt.KINDS, t["id"]
        assert t["criterion"].strip() and t["name"].strip() and t["cls"].strip(), t["id"]
        assert t["can_fail"].strip(), f"{t['id']}: say whether and how the check can fail"
        assert t["id"].startswith(f"L{t['level']}."), t["id"]
        if t["status"] == "blocked":
            assert t.get("blocker"), t["id"]
        if t["status"] in ("pass", "formal", "fail", "inconclusive", "uninformative", "not_applied"):
            assert t.get("evidence"), f"{t['id']}: a measured status needs a source"


def test_code_checks_are_exactly_the_agreed_ones():
    assert {t["id"] for t in vt.load()["tests"] if t["kind"] == "code"} == {"L1.1", "L1.2", "L1.3", "L1.4", "L1.5", "L1.6", "L1.12"}


def test_a_check_that_was_not_run_cannot_have_a_criterion_written_after_the_result():
    for t in vt.load()["tests"]:
        if t["status"] in ("not_run", "blocked"):
            assert t["declared"] == "before_run", t["id"]


def test_a_formal_pass_says_that_it_could_hardly_fail():
    for t in vt.load()["tests"]:
        if t["status"] == "formal":
            assert "Почти не может" in t["can_fail"], t["id"]


def test_checks_with_few_units_carry_a_minimum_and_the_primary_test_has_the_power_rule():
    spec = vt.load()
    by = {t["id"]: t for t in spec["tests"]}
    for i in ("L3.3", "L3.4", "L3.5"):
        assert by[i]["min_units"]["scored"] >= 30 and by[i]["min_units"]["positives"] >= 8, i
    assert by["L3.3"]["min_units"]["mde_auc"] == 0.78
    assert "30" in spec["power"]["rule"] and "неинформативно" in spec["power"]["rule"]
    assert {i for i in spec["multiplicity"]["family"]} == {"L3.4", "L3.5"} and by["L3.4"]["multiplicity"] and by["L3.5"]["multiplicity"]
    assert "multiplicity" not in by["L3.3"]


def test_noise_relative_thresholds_for_paraphrase_and_style():
    by = {t["id"]: t for t in vt.load()["tests"]}
    for i in ("L1.8", "L1.9"):
        assert "повтор" in by[i]["criterion"] and "минус 0.05" in by[i]["criterion"], i
    assert "0.9" not in by["L1.9"]["criterion"] and "90%" not in by["L1.8"]["criterion"]


def test_a_tie_on_a_historical_pool_is_not_a_failure():
    by = {t["id"]: t for t in vt.load()["tests"]}
    assert by["L2.2"]["status"] == "inconclusive" and "A1" in by["L2.2"]["can_fail"]


def test_clean_policy_lists_a_as_main_and_is_not_yet_confirmed():
    cp = vt.load()["clean_policy"]
    assert cp["confirmed"] is False and cp["main_test"].startswith("А:") and cp["separate"].startswith("В:") and cp["background"].startswith("Б:")
    assert all(re.fullmatch(r"20\d\d-\d\d-\d\d", c["stated_cutoff"]) and c["source"].startswith("https://") for c in cp["feasibility_of_A"]["candidates"])


def test_evidence_paths_exist():
    for t in vt.load()["tests"]:
        for part in (t.get("evidence") or "").split(";"):
            path = re.split(r" \(", part.strip())[0].strip()
            if path.startswith(("docs/", "tests/", "hyparena/", "scripts/", "specs/")):
                assert Path(path).exists(), f"{t['id']}: {path}"


def test_the_summary_keeps_the_three_tallies_apart():
    text = vt.render(vt.load())
    assert "**Проверки кода и метода** (7)" in text and "**Проверки утверждения об отборе** (21)" in text
    assert "с критерием, зафиксированным до результата:" in text


def test_the_rendered_table_is_up_to_date():
    assert vt.OUT.read_text(encoding="utf-8") == vt.render(vt.load())


def test_the_candidate_acceptance_criterion_is_fixed_before_the_check_and_relative_to_noise():
    by = {t["id"]: t for t in vt.load()["tests"]}
    t = by["L1.13"]
    assert t["declared"] == "before_run" and t["status"] == "uninformative" and t.get("evidence")
    th = t["thresholds"]
    # the thresholds are the measured noise of the repeat (docs/rules-method.md, paired check) minus the named tolerances
    assert abs(th["stance_agree_min"] - (96 / 99 - 0.05)) < 0.006 and abs(th["effect_agree_min"] - (95 / 99 - 0.05)) < 0.006
    assert abs(th["set_agree_min"] - (53 / 64 - 0.10)) < 0.001
    assert th["completion_token_cap"] == 4000 and th["mini_sample"] == {"valid_min": 7, "truncated_max": 1}
    cfg = Path("configs/v2-gpt5.yaml").read_text()
    assert "max_completion_tokens: 4000" in cfg and "reasoning_effort: minimal" in cfg and '"gpt-5"' in cfg


def test_the_status_level_criteria_are_tied_to_the_repeat_noise_and_fixed_before_any_candidate_run():
    by = {t["id"]: t for t in vt.load()["tests"]}
    th = by["L1.14"]["thresholds"]
    assert by["L1.14"]["declared"] == "before_run"
    assert abs(th["call_rate_min"] - (th["noise_call_rate"] - 0.05)) < 0.006 and abs(th["jaccard_min"] - (th["noise_jaccard"] - 0.05)) < 0.006
    for k in ("L1.15", "L1.16"):
        t = by[k]
        assert t["declared"] == "before_run" and t["status"] == "not_run"
        assert {x: t["thresholds"][x] for x in ("call_rate_min", "jaccard_min", "counted_union_min")} == \
               {x: th[x] for x in ("call_rate_min", "jaccard_min", "counted_union_min")}
    assert by["L1.15"]["thresholds"]["completion_token_cap"] == 4000 and "gpt-5.1" in Path("configs/v2-gpt51.yaml").read_text()
    assert "NOT eligible" in Path("configs/v2-gemini31pro.yaml").read_text()

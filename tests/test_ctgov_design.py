from scripts.benchmark_run import _ctgov_design, _text

P = {"designModule": {"designInfo": {"allocation": "RANDOMIZED", "interventionModel": "PARALLEL",
                                     "primaryPurpose": "PREVENTION",
                                     "maskingInfo": {"masking": "SINGLE", "whoMasked": ["OUTCOMES_ASSESSOR"]}},
                      "enrollmentInfo": {"count": 60, "type": "ESTIMATED"}},
     "armsInterventionsModule": {"armGroups": [{"label": "Squat group", "type": "EXPERIMENTAL", "description": "Squats 3x/week"},
                                               {"label": "Control", "type": "NO_INTERVENTION"}]}}


def test_design_arms_and_planned_enrollment_enter_the_text():
    f = dict(_ctgov_design(P))
    assert f["Design"] == "randomized, parallel, masking single (outcomes assessor), primary purpose prevention"
    assert f["Arms"] == "Squat group (experimental): Squats 3x/week; Control (no intervention)"
    assert f["Planned enrollment"] == "60"
    t = _text(_ctgov_design(P))
    assert t.splitlines()[0].startswith("Design: randomized")


def test_an_actual_enrollment_is_left_out_and_missing_fields_are_skipped():
    p = {"designModule": {"enrollmentInfo": {"count": 58, "type": "ACTUAL"}}}
    assert _text(_ctgov_design(p)) == ""

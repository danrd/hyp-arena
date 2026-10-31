from scripts import ctgov_outcomes as co


def test_only_prospective_registrations_are_kept():
    assert co.prospective({"written_on": "2015-01-10", "primary_completion": "2016-03"})
    assert not co.prospective({"written_on": "2019-11-05", "primary_completion": "2016-08-20"})
    assert not co.prospective({"written_on": "2015-01-10", "primary_completion": ""})


def test_a_label_counts_only_with_a_verbatim_quote_from_the_named_source():
    row = {"sources": [{"id": "R", "text": "Analysis (A, B); ANCOVA; p-value 0.03"}, {"id": "P1", "text": "Grip strength did not differ."}]}
    assert co.verify_quote({"source": "R", "quote": "p-value 0.03"}, row)
    assert co.verify_quote({"source": "P1", "quote": "grip  strength did not differ."}, row)
    assert not co.verify_quote({"source": "P1", "quote": "p-value 0.03"}, row)
    assert not co.verify_quote({"source": "P2", "quote": "anything"}, row)


def test_the_prompt_renders_with_the_inputs():
    from hyparena.llm.prompts import render
    text = render("label_trial_outcome", "v1", nct="NCT0", title="T", interventions="X", primary_outcomes=[{"measure": "M", "time_frame": "6 mo"}],
                  sources=[{"id": "R", "kind": "posted results", "text": "p-value 0.2"}])
    assert "NCT0" in text and "[R] posted results" in text and '"label"' in text


def test_a_source_id_copied_with_brackets_is_accepted():
    row = {"sources": [{"id": "P1", "text": "Falls did not differ."}]}
    assert co.verify_quote({"source": "[P1]", "quote": "Falls did not differ."}, row)

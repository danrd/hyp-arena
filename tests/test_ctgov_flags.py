from scripts.ctgov_flags import overlap, posted_primary, sentences_with_hits, words


def test_phrases_hit_own_result_and_skip_plans():
    assert sentences_with_hits("Aim: test X. No significant effects were found; however, adherence was poor.")
    assert sentences_with_hits("We found that X improved Y.")
    assert not sentences_with_hits("We will test whether X improves Y. The primary outcome is gait speed.")


def test_overlap_ignores_stop_words():
    assert overlap(words("Change in Gait Speed From Baseline"), words("Gait speed (m/s)")) == 1.0
    assert overlap(words("Grip strength"), words("Gait speed")) == 0.0


def test_posted_primary_names():
    row = {"sources": [{"id": "R", "text": "Primary outcome: Gait Speed (m/s; MEAN; 12 weeks) | Primary outcome: Grip (kg; MEAN; 1 day)"}]}
    assert posted_primary(row) == ["Gait Speed", "Grip"]
    assert posted_primary({"sources": []}) == []

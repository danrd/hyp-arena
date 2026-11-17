from scripts.argon.pack29_reviews import t_of


def test_t_is_the_year_by_which_half_of_the_studies_were_published():
    assert t_of([2001, 2005, 2010, 2015]) == (2005, True)
    assert t_of([2001, 2005, 2010]) == (2005, True)          # 2 of 3 by 2005
    assert t_of([2010, 2010, 2010]) == (2010, False)         # nothing after T: the review adds no later trial
    assert t_of([]) == (None, False)

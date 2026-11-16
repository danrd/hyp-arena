"""Written hypotheses (not registry trials): a declared alternative has no link; an ordinal value outside its levels is unknown."""
from hyparena.card.models import DeclaredAlternative, Entity
from hyparena.scoring import aspid_v3


def test_an_ordinal_value_outside_the_levels_is_unknown():
    assert aspid_v3._known_level("endpoint_clinical", "other") is None
    assert aspid_v3._known_level("endpoint_clinical", "function") == "function"
    assert aspid_v3._known_level("chain_state", 0.4) == 0.4


def test_the_population_query_reads_a_declared_alternative():
    from hyparena.search.search import population_query
    alt = DeclaredAlternative(id="a1", subject=Entity(label="x"), relation="promotes", object=Entity(label="y"), source_span="x")
    assert not hasattr(alt, "link")
    try:
        population_query(alt, None)
    except AttributeError as e:
        assert "link" not in str(e), e
    except Exception:
        pass

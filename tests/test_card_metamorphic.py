from pathlib import Path
import pytest
import yaml

from hyparena.card.models import HypothesisCard, Verification, Intervention
from hyparena.card.rules import finalize, statuses
from hyparena.card import verifier
from hyparena.tools import pubmed

FIX = Path(__file__).parent / "fixtures" / "cards"

def _stub(monkeypatch: pytest.MonkeyPatch, abstracts: dict, records: list) -> None:
    """Mocks pubmed search and fetch, and verifier ask calls to return static records without network calls."""
    def fetch(ids):
        return {id: abstracts[id] for id in ids if id in abstracts}
    monkeypatch.setattr(pubmed, "search", lambda q, retmax=8, as_of=None: list(abstracts.keys()))
    monkeypatch.setattr(pubmed, "fetch", fetch)
    monkeypatch.setattr(verifier, "drugage_records", lambda claim, allowed=None, cid=None: ([], []))
    monkeypatch.setattr(verifier, "ask", lambda *a, **k: ({"records": records}, "fake"))


def base_case() -> tuple[HypothesisCard, Verification]:
    """Loads Example 5 card and verification as a clean slate for metamorphic testing."""
    d = yaml.safe_load((FIX / "ex5_resveratrol_endpoint.yaml").read_text(encoding="utf-8"))
    card = HypothesisCard.model_validate(d["card"])
    ver = Verification.model_validate(d["verification"])
    return card, ver

def get_abstract(pmid: int, quote: str, title: str = "Resveratrol extends lifespan in mice.") -> dict:
    """Helper to generate a mock PubMed abstract dictionary."""
    return {
        "pmid": str(pmid),
        "title": title,
        "year": "2020",
        "pubtypes": ["Journal Article"],
        "abstract": quote,
        "first_author": "X",
        "journal": "J"
    }

def record_dict(pmid: str = "1", **kw) -> dict:
    """Helper to construct an evidence record dictionary mock."""
    d = {
        "pmid": str(pmid),
        "species": "mouse",
        "endpoint": "lifespan",
        "quote_role": "finding",
        "effect": "increase",
        "quote": "resveratrol extends median lifespan",
        "qualifiers_match": {"intervention_match": "exact"}
    }
    d.update(kw)
    return d

def make_combination(card):
    from hyparena.card import entities
    card.pico.intervention.append(Intervention(type="compound", label="rapamycin", id="CHEBI:9168"))
    c1 = card.claims[0]
    c1.subject.id = "CHEBI:27881+CHEBI:9168"
    c1.subject.label = "resveratrol and rapamycin"
    entities.resolve_card(card)

CASES = [
    # 1. species mismatch
    (
        "species_mismatch",
        lambda card: None,
        {"1": get_abstract(1, "resveratrol extends median lifespan of humans")},
        [record_dict(1, species="human", quote="resveratrol extends median lifespan of humans")],
        "unverified",
        lambda card, ver, cv: len(cv.evidence) == 1 and cv.evidence[0].qualifiers_match.get("species") == "no"
    ),
    # 2. direction shortens
    (
        "direction_shortens",
        lambda card: setattr(card.claims[0], "relation", "shortens_lifespan_in"),
        {"1": get_abstract(1, "resveratrol extends median lifespan")},
        [record_dict(1, effect="increase")],
        "refuted",
        lambda card, ver, cv: len(cv.counterevidence) == 1 and cv.counterevidence[0].effect == "increase"
    ),
    # 4. quote role background
    (
        "quote_role_background",
        lambda card: None,
        {"1": get_abstract(1, "resveratrol extends median lifespan")},
        [record_dict(1, quote_role="assumption")],
        "unverified",
        lambda card, ver, cv: len(cv.evidence) == 0
    ),
    # 6. sex scope both
    (
        "sex_scope_both",
        lambda card: setattr(card.claims[0], "sex_scope", "both"),
        {
            "1": get_abstract(1, "resveratrol extends median lifespan for males"),
            "2": get_abstract(2, "it had no effect on females")
        },
        [
            record_dict(1, sex="male", effect="increase", quote="resveratrol extends median lifespan for males"),
            record_dict(2, sex="female", effect="no_effect", quote="it had no effect on females")
        ],
        "contested",
        lambda card, ver, cv: len(cv.evidence) == 1 and len(cv.counterevidence) == 1
    ),
    # 6. sex scope any
    (
        "sex_scope_any",
        lambda card: setattr(card.claims[0], "sex_scope", "any"),
        {
            "1": get_abstract(1, "resveratrol extends median lifespan for males"),
            "2": get_abstract(2, "it had no effect on females")
        },
        [
            record_dict(1, sex="male", effect="increase", quote="resveratrol extends median lifespan for males"),
            record_dict(2, sex="female", effect="no_effect", quote="it had no effect on females")
        ],
        "supported",
        lambda card, ver, cv: "other_sex_null" in cv.flags
    ),
    # 8. endpoint mismatch
    (
        "endpoint_mismatch",
        lambda card: None,
        {"1": get_abstract(1, "resveratrol extends median lifespan")},
        [record_dict(1, endpoint="mechanism")],
        "unverified",
        lambda card, ver, cv: len(cv.evidence) == 0 and any("endpoint" in r.type for r in cv.refusals)
    ),
    # 9. different compound (combination)
    (
        "combination_compound",
        make_combination,
        {"1": get_abstract(1, "resveratrol extends median lifespan", title="Resveratrol extends lifespan")},
        [record_dict(1, quote="resveratrol extends median lifespan")],
        "unverified",
        lambda card, ver, cv: len(cv.evidence) == 1 and cv.evidence[0].qualifiers_match.get("intervention_match") == "related_compound"
    ),
    # 9. different compound (related_compound via code check for a completely different compound)
    (
        "related_compound",
        lambda card: None,
        {"1": get_abstract(1, "malate extends median lifespan", title="Malate extends lifespan")},
        [record_dict(1, quote="malate extends median lifespan")],
        "unverified",
        lambda card, ver, cv: len(cv.evidence) == 1 and cv.evidence[0].qualifiers_match.get("intervention_match") == "related_compound"
    ),
    # 10. adding records
    (
        "adding_records",
        lambda card: None,
        {
            "1": get_abstract(1, "resveratrol extends median lifespan"),
            "2": get_abstract(2, "extends the lifespan of diverse species")
        },
        [
            record_dict(1, effect="increase", quote="resveratrol extends median lifespan", lab_or_cohort="1"),
            record_dict(2, effect="increase", quote="extends the lifespan of diverse species", lab_or_cohort="2")
        ],
        "supported",
        lambda card, ver, cv: len(cv.evidence) == 2 and statuses(card, ver).get(cv.id) == "supported" and ver.evidence_profile.robustness == "replicated"
    ),
    (
        "adding_refuting_to_supported",
        lambda card: None,
        {
            "1": get_abstract(1, "resveratrol extends median lifespan"),
            "2": get_abstract(2, "did not extend lifespan")
        },
        [
            record_dict(1, effect="increase", quote="resveratrol extends median lifespan"),
            record_dict(2, effect="no_effect", quote="did not extend lifespan")
        ],
        "contested",
        lambda card, ver, cv: statuses(card, ver).get(cv.id) == "contested"
    ),
]

@pytest.mark.parametrize("name, modify_card, abstracts, records, expected_status, check_extra", CASES)
def test_metamorphic(monkeypatch: pytest.MonkeyPatch, name: str, modify_card, abstracts: dict, records: list, expected_status: str, check_extra) -> None:
    """Metamorphic test that modifies one field of a card or evidence and checks the rules' reaction."""
    card, ver = base_case()

    cv = next(c for c in ver.claims if c.id == card.claims[0].id)
    cv.evidence = []
    cv.counterevidence = []
    cv.refusals = []

    modify_card(card)

    pmids = list(dict.fromkeys(r["pmid"] for r in records))
    monkeypatch.setattr(pubmed, "search", lambda q, retmax=8, as_of=None: pmids)
    def fetch(ids):
        return {id: abstracts[id] for id in ids if id in abstracts}
    monkeypatch.setattr(pubmed, "fetch", fetch)
    monkeypatch.setattr(verifier, "drugage_records", lambda claim, allowed=None, cid=None: ([], []))
    monkeypatch.setattr(verifier, "ask", lambda *a, **k: ({"records": records}, "fake"))

    cv_new = verifier.verify_claim(None, "google", frozenset(), card.claims[0], card)

    for i, claim_ver in enumerate(ver.claims):
        if claim_ver.id == cv_new.id:
            ver.claims[i] = cv_new
            break

    ver = finalize(card, ver)

    cv = next(c for c in ver.claims if c.id == card.claims[0].id)

    assert cv.status == expected_status
    assert check_extra(card, ver, cv)

"""Cross-link reading (reading benchmark, cross_link_reading_2026_11_15): a claim of the hypothesis (outcome or step) also
reads the papers the hypothesis's other searches found - mostly those of its proposed alternatives, which are otherwise
read only against the alternative (where a finding counts only by its distinguishing part). The cheap relevance model rates
those papers for the claim, as in the search (hyparena/search/search.py relevance), and the claim reads every one rated 3,
filled up to 10 with those rated 2, at most 20. New records join the claim's records; the alternatives keep their own.

On the 30 trials of pack 18 (reader v16 in batches of 10): gold papers that became records 0.27 -> 0.38, the AUC of the
evidence balance against the outcomes 0.66 -> 0.71; about 0.013 USD per hypothesis."""
from __future__ import annotations

from typing import Optional

from hyparena.card.models import ClaimVerification, HypothesisCard, Verification


def searched_by_claim(log: list) -> dict[str, list[str]]:
    """{claim id: the papers its search gave the reader} from the search entries of one hypothesis's log."""
    out: dict[str, list[str]] = {}
    for e in log:
        if e.get("kind") == "search" and e.get("claim"):
            out.setdefault(e["claim"], [])
            out[e["claim"]] += [p for p in e.get("pmids") or [] if p not in out[e["claim"]]]
    return out


def queries_of(log: list, claim_id: str) -> list[str]:
    q = [e for e in log if e.get("kind") == "search_plan" and e.get("claim") == claim_id]
    return list(q[0].get("guarded") or q[0].get("model_queries") or []) if q else []


def cross_read(client, family: str, avoid: frozenset, card: HypothesisCard, cvs: list[ClaimVerification],
               searched: dict[str, list[str]], as_of: Optional[str], template_version: str, log: Optional[list] = None,
               fallback: Optional[str] = None, queries: Optional[dict[str, list[str]]] = None) -> tuple[list[ClaimVerification], dict]:
    """The claims' verifications with the records of the cross-link reading added, and what was read per claim."""
    from hyparena.reading.verifier import verify_claim
    from hyparena.search import search as srch, search_rank as rank
    from hyparena.tools import pubmed
    everything = list(dict.fromkeys(p for v in searched.values() for p in v))
    recs = pubmed.fetch(everything) if everything else {}
    claims = {c.id: c for c in card.claims if c.part != "premise"}
    added, out = {}, []
    for cv in cvs:
        claim = claims.get(cv.id)
        if claim is None:
            out.append(cv)
            continue
        own = searched.get(cv.id, [])
        extra = [p for p in everything if p not in own and (recs.get(p) or {}).get("abstract")]
        scores = srch.relevance(client, avoid, claim, card, (queries or {}).get(cv.id, []), extra, recs, log=log) if extra else {}
        pick = rank.select(extra, scores, fill=srch.FILL, cap=srch.CAP)
        added[cv.id] = {"extra": len(extra), "ratings": {k: sum(1 for v in scores.values() if v == k) for k in (0, 1, 2, 3)},
                        "read": pick}
        if pick:
            new_cv = verify_claim(client, family, avoid, claim, card, as_of, log=log, fallback=fallback,
                                  expert_pmids=[(p, "cross-link: another search of the hypothesis") for p in pick],
                                  search="fixed", template_version=template_version)
            seen = {r.record_id for r in cv.evidence + cv.counterevidence}
            cv.evidence += [r for r in new_cv.evidence if r.record_id not in seen]
            cv.counterevidence += [r for r in new_cv.counterevidence if r.record_id not in seen]
            cv.no_stance += new_cv.no_stance
        out.append(cv)
    return out, added


def refinalize(card: HypothesisCard, verification: Verification, cvs: list[ClaimVerification]) -> Verification:
    from hyparena.scoring.rules import finalize
    return finalize(card, Verification(card_id=card.id, claims=cvs, searched_pmids=verification.searched_pmids))

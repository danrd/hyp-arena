"""Verifier: claim → evidence records (card spec section 7). Sources: DrugAge (curated, deterministic, lifespan
claims) and PubMed abstracts (an LLM extracts records). Code then checks that every quote is a verbatim
substring of its abstract, drops those that are not, and leaves statuses to the rules."""
from __future__ import annotations

import re
from typing import Optional

from hyparena.card.llm import ask, parse_objects
from hyparena.card.models import (UNKNOWN, Claim, ClaimVerification, Entity, EvidenceRecord,
                                  HypothesisCard, ProgramInfo, Refusal, Verification)
from hyparena.card.rules import (HUMAN_RUNGS, ORGANISM_PATTERNS, add_disease_analogs, add_strain_analogs, admissible, claim_organism,
                                 claim_endpoint, mark_strata, pico_value, prespecified_sex, quote_organisms, species_key,
                                 subgroup_only)
from hyparena.card import contexts
from hyparena.card.entities import subject_compounds
from hyparena.tools.compounds import split as split_label
from hyparena.card.sources import curated_intervention_match, drugage_records, lifespan_wanted
from hyparena.tools import pubmed, trials

TEMPLATE = ("verify_claim", "v5")
SUBGROUP_TEMPLATE = ("check_subgroup", "v1")
NCT = re.compile(r"\bNCT\d{8}\b")
# PubMed's Best Match order is not deterministic: the same query a second later returns another top 8 (only 4 of 12
# PMIDs were in all of 6 repeats); the top 20 is nearly stable (18 of 22), so 20 abstracts per claim (2026-10-21)
RETMAX = 20
ALTERNATIVE_RETMAX = 20
REL_WORDS = {"extends_lifespan_in": "lifespan", "shortens_lifespan_in": "lifespan", "no_lifespan_effect_in": "lifespan",
             "slows_aging_in": "slows aging",
             "improves_healthspan_in": "healthspan OR physical function", "changes_biomarker": "", "predicts": "predicts",
             "inhibits": "inhibits", "activates": "activates", "increases_expression": "expression",
             "decreases_expression": "expression", "promotes": "", "suppresses": "", "part_of": "",
             "associated_with": "", "affects_hallmark": "", "translates_to": "", "other": ""}


def _clean(s: str) -> str:
    return re.sub(r"[\"'()\[\]/]", " ", s or "").strip()


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").replace("‐", "-").replace("–", "-")).strip().lower()


SPECIES_WORDS = {"older adults": "humans", "healthy older adults": "humans", "adults": "humans", "human": "humans",
                 "mouse": "mice", "mice": "mice", "rat": "rats", "nematode": "C. elegans", "worm": "C. elegans",
                 "fly": "Drosophila", "yeast": "yeast"}


def _core(label: str, card: HypothesisCard) -> str:
    """The entity name for a search: the card's intervention label when the claim subject contains it
    (drops regimen words such as "weekly low-dose")."""
    low = label.lower()
    hits = [i.label for i in card.pico.intervention if i.label.lower() in low]
    return " ".join(hits) if hits else label


def queries(claim, card: HypothesisCard) -> list[str]:
    """Search terms: entity, relation word, object; the organism as a search word. When the object is not an
    organism, also the relation alone ("rapamycin slows aging mice"): long object phrases often match nothing.
    When it is, the claim's `measure`. The first query excludes reviews."""
    subject = _core(claim.subject.label, card)
    obj = claim.object.label
    organism = SPECIES_WORDS.get(obj.strip().lower()) or SPECIES_WORDS.get(claim.qualifiers.get("species", "").strip().lower(), "")
    obj_term = "" if obj.strip().lower() in SPECIES_WORDS else obj
    rel = REL_WORDS.get(claim.relation, "")
    if " OR " in rel:                    # PubMed binds AND tighter than OR: without brackets "X healthspan OR physical function
        rel = f"({rel})"                 # humans" is "(X healthspan) OR (physical function humans)" (calibration, 2026-11-02)

    def q(*words):                       # the relation words keep their brackets; entity labels are cleaned
        return " ".join(w if w == rel else _clean(w) for w in words if w and w != UNKNOWN)

    measure = claim.qualifiers.get("measure", "") if not obj_term else ""
    q1 = q(subject, rel, obj_term, organism)
    q_rel = q(subject, rel, organism) if rel and obj_term and organism else ""
    q2 = q(subject, obj_term or organism)
    # "lifespan" only for lifespan claims (H49 walkthrough 2026-11-11: it was added to every claim, "squat exercise body
    # composition humans lifespan")
    lifespan_claim = claim.relation in ("extends_lifespan_in", "shortens_lifespan_in", "no_lifespan_effect_in")
    q3 = q(subject, obj_term, organism, "lifespan" if lifespan_claim and "lifespan" not in q1 else "")
    q_measure = q(subject, measure, organism) if measure else ""
    # primary research first: reviews only give background (never a status) and push findings out of the top
    # results; without them the first page holds the studies on both sides (Example 3: Wilkinson 2012 and Neff 2013)
    q_primary = f"{q1} NOT review[pt]" if q1 else ""
    main = [x for x in (q_primary, q1, q_rel, q2, q3, q_measure) if x]
    # Fallbacks for trial-style claims (benchmark pilot, 2026-11-01; specs/benchmark-v2-run.yaml): a long object phrase
    # ("markers of inflammation, immune system markers and other ...") and a subject made of several intervention labels
    # match nothing when every word is required. Appended last, so they run only when the queries above found fewer than
    # `retmax` papers: the head of the object phrase, the first intervention alone, the population words instead of "humans".
    subj_short = _words(_first_intervention(claim.subject.label, card), 5)
    obj_head = _words(_head(obj_term), 4)
    pop = _population_words(card) if organism == "humans" else ""
    fallbacks = [q(subj_short, obj_head, pop or organism), q(subj_short, obj_head)] if obj_head else [q(subj_short, organism)]
    if obj_head and pop:                     # human claims only: the outcome in the population without the intervention name
        fallbacks.append(q(obj_head, pop))
    fallbacks = [x for x in fallbacks if x and (subj_short != subject or obj_head != obj_term or pop)]
    return list(dict.fromkeys(main + fallbacks))


_STOP = {"the", "a", "an", "of", "in", "on", "to", "and", "or", "other", "its", "their", "with", "for", "by"}


def _words(text: str, n: int) -> str:
    """The first `n` content words (stop words dropped, the order kept)."""
    return " ".join([w for w in _clean(text).split() if w.lower() not in _STOP][:n])


def _head(phrase: str) -> str:
    """The head of an object phrase: up to the first comma, semicolon, "and", "or" or "as well as"."""
    return re.split(r",|;|\band\b|\bor\b|\bas well as\b", phrase or "", maxsplit=1)[0].strip()


def _first_intervention(label: str, card: HypothesisCard) -> str:
    """The first intervention of the card named in the claim subject (a probe's subject joins all of them)."""
    low = (label or "").lower()
    hits = [i.label for i in card.pico.intervention if i.label and i.label.lower() in low]
    return hits[0] if hits else label


def _population_words(card: HypothesisCard) -> str:
    """Short population words for a human claim ("older adults", "frail elderly"), else nothing."""
    label = _clean(card.pico.population.label or "")
    words = label.split()
    if not 1 <= len(words) <= 3 or label.lower() in ("human", "humans", "unknown"):
        return ""
    return label


def names_intervention(claim, card: HypothesisCard, text: str) -> bool:
    """Does the text name the claim's compound (or every component of a combination), by name or synonym?
    True when the subject is not a resolved compound: then there is nothing to check by name."""
    comps = subject_compounds(claim.subject.label, card)
    if not comps:
        return True
    low = " " + re.sub(r"[‐-―−]", "-", text.lower()) + " "
    for part, c in zip(split_label(claim.subject.label), comps):     # each component by its own names
        names = {n.lower() for n in [part, c.name, *c.synonyms] if len(n) >= 4 and not re.fullmatch(r"[\d-]+", n)}
        if not any(re.search(rf"(?<![a-z0-9]){re.escape(n)}(?![a-z0-9])", low) for n in names):
            return False
    return True


GENERIC = re.compile(r"\b(?:senolytics?|senomorphics?|the (?:drugs?|compounds?|combination|treatment|intervention|agents?)"
                     r"|these (?:drugs|compounds|agents)|this (?:drug|compound|combination|treatment))\b", re.I)


def names_in_source(claim, card: HypothesisCard, title: str, abstract: str, quote: str) -> bool:
    """The record is about the claim's intervention: the title or the quote names it, or the quote refers to it
    generically ("senolytics", "the combination") in an abstract that names it (Xu et al. 2018: "intermittent
    oral administration of senolytics" in an abstract about dasatinib plus quercetin)."""
    if names_intervention(claim, card, title + " " + quote):
        return True
    return bool(GENERIC.search(quote)) and names_intervention(claim, card, title + " " + abstract)


def mark_subgroup(evidence: list[EvidenceRecord], counter: list[EvidenceRecord]) -> None:
    """A trial result in one sex only, from a paper whose other result for the same claim is null or negative,
    is a post hoc subgroup result (PEARL: "improved significantly for women using 10 mg", primary outcome null). Set by
    code when the extractor left the flag out. Not for a protocol that fixed sex as a stratum in advance (ITP, CITP)."""
    mark_strata(evidence + counter)                       # ITP and CITP fix sex as a stratum in advance
    against = {r.record_id for r in counter if r.record_id.startswith("PMID:")}
    for r in evidence:
        if r.record_id in against and r.sex in ("male", "female") and "subgroup_only" not in r.flags and not prespecified_sex(r):
            r.flags.append("subgroup_only")
            r.notes += "; subgroup_only set by code: one sex, and a null result for the claim in the same paper"


def _context_match(qm: dict[str, str], claim, card: HypothesisCard, quote: str = "") -> dict[str, str]:
    """Spec 7: a qualifier the card leaves unknown gives n/a, never a mismatch."""
    out = dict(qm)
    out.pop("strain", None)                               # strain is compared by code (rules.strain_match)
    for key in ("sex", "age_at_start", "dose", "comparator"):
        value = claim.qualifiers.get(key) or (pico_value(card, key) if key != "dose"
                                              else next((i.regimen for i in card.pico.intervention), UNKNOWN))
        if out.get(key) == "no" and (not value or value.strip().lower() in (UNKNOWN, "", "n/a")):
            out[key] = "n/a"
        elif key == "dose" and out.get(key) == "no" and not re.search(r"\d", value or ""):
            out[key] = "n/a"                               # a dose in words ("low-dose") is not a number to contradict
    if out.get("species") == "no" and not claim_organism(claim):
        out["species"] = "n/a"                             # the claim names no organism: unknown, not a mismatch
    # the quote names organisms and the claim's is not among them (e.g. a sentence about yeast, worms and flies
    # extracted as a mouse finding): a species mismatch, whatever the extractor said
    organism = species_key(claim.qualifiers.get("species", "")) or species_key(claim.object.label)
    named = quote_organisms(quote)
    if organism in ORGANISM_PATTERNS and named and organism not in named:
        out["species"] = "no"
    return out


def parse_records(text: str) -> Optional[dict]:
    """{"records": [...]}; from a reply cut off at the token limit, the records that are complete."""
    found = parse_objects(text)
    whole = next((v for v in found if isinstance(v.get("records"), list)), None)
    if whole is not None:
        return whole
    records = [v for v in found if "pmid" in v and "quote" in v]
    return {"records": records, "truncated": True} if records else None


def _validate(value: dict, abstracts: dict[str, dict]) -> list[str]:
    if not isinstance(value.get("records"), list):
        return ['the reply must be an object with a "records" list']
    problems = ["the reply was cut off before the end: reply again, complete"] if value.get("truncated") else []
    for i, r in enumerate(value.get("records") or []):
        if not isinstance(r, dict):
            problems.append(f"record {i}: not an object")
            continue
        pmid = str(r.get("pmid", "")).replace("PMID:", "").strip()
        a = abstracts.get(pmid)
        if a is None:
            problems.append(f"record {i}: PMID {pmid} is not one of the given abstracts")
        elif _norm(r.get("quote", "")) not in _norm(a["title"] + " " + a["abstract"]):
            problems.append(f"record {i} (PMID {pmid}): the quote is not copied verbatim from the abstract")
    return problems


def curated(claim, card: HypothesisCard, as_of: Optional[str] = None) -> tuple[list[EvidenceRecord], list[EvidenceRecord]]:
    """DrugAge records for a lifespan claim (deterministic), restricted to papers published by `as_of`."""
    comps = subject_compounds(claim.subject.label, card)
    support, against = drugage_records(claim, cid=comps[0].cid if comps and len(comps) == 1 else None)
    for r in support + against:
        r.qualifiers_match["intervention_match"] = curated_intervention_match(card, r)
    if as_of and (support or against):
        from hyparena.backtest import _pubdates
        dates = _pubdates([r.linked_pmid for r in support + against])
        allowed = {p for p, d in dates.items() if d <= as_of}
        support = [r for r in support if r.linked_pmid in allowed]
        against = [r for r in against if r.linked_pmid in allowed]
    return support, against


def date_guard(pmids: list[str], as_of: Optional[str]) -> tuple[list[str], dict[str, str]]:
    """A run on date T keeps only papers first public on or before T. The search already asks PubMed for that, but
    the sources an expert gave and the search's own date field are not trusted: every PMID is dated with PubMed's
    earliest public date. A PMID without a date is dropped. Returns (kept, {dropped pmid: reason})."""
    if not as_of or not pmids:
        return list(pmids), {}
    from hyparena import backtest
    dates = backtest._pubdates(list(pmids))
    kept, dropped = [], {}
    for p in pmids:
        if p not in dates:
            dropped[p] = "undated"
        elif dates[p] > as_of:
            dropped[p] = f"after_T {dates[p]}"
        else:
            kept.append(p)
    return kept, dropped


def recheck(claim, card: HypothesisCard, evidence: list[EvidenceRecord], counter: list[EvidenceRecord]
            ) -> tuple[list[EvidenceRecord], list[EvidenceRecord]]:
    """The code checks of `verify_claim` applied again to saved PubMed records (abstracts from the cache):
    the compound named in the quote or the title, context flags, and the stance of lifespan findings set from
    their extracted direction. Returns (evidence, counterevidence)."""
    abstracts = pubmed.fetch(sorted({r.record_id.replace("PMID:", "") for r in evidence + counter}))
    need = claim_endpoint(claim)
    out_for, out_against = [], []
    for side, records in (("supports", evidence), ("refutes", counter)):
        for r in records:
            r = r.model_copy(deep=True)
            a = abstracts.get(r.record_id.replace("PMID:", "")) or {"title": "", "abstract": ""}
            contexts.flag(r, a["title"] + " " + a["abstract"])
            if r.qualifiers_match.get("intervention_match", "exact") in ("exact", "dose_differs", "regimen_differs") \
                    and a["title"] and not names_in_source(claim, card, a["title"], a["abstract"], r.quote):
                r.qualifiers_match["intervention_match"] = "related_compound" if subject_compounds(claim.subject.label, card) else "class"
                r.notes += "; the quote and the title do not name the intervention: counted as a related compound"
            stance = side
            if need == "lifespan" and r.endpoint == "lifespan" and r.quote_role == "finding" and r.effect != "unknown":
                stance = "supports" if r.effect == lifespan_wanted(claim) else "refutes"
            (out_for if stance == "supports" else out_against).append(r)
    mark_subgroup(out_for, out_against)
    return out_for, out_against


V3_DESIGNS = ("rct", "non_randomised", "observational", "animal", "cells", "review", "meta_analysis", "other")
_UNITS = {w: i for i, w in enumerate("zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen "
                                     "fifteen sixteen seventeen eighteen nineteen".split())}
_TENS = {w: 10 * i for i, w in enumerate("_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()) if w != "_"}


def words_to_numbers(text: str) -> set[int]:
    """Numbers written in English words in a phrase ("One hundred and sixty-three outpatients" -> {163})."""
    out, cur, total, seen = set(), 0, 0, False
    for w in re.findall(r"[a-z]+", (text or "").lower().replace("-", " ")):
        if w in _UNITS:
            cur += _UNITS[w]; seen = True
        elif w in _TENS:
            cur += _TENS[w]; seen = True
        elif w == "hundred" and seen:
            cur *= 100
        elif w == "thousand" and seen:
            total += cur * 1000; cur = 0
        elif w == "and" and seen:
            continue
        elif seen:
            out.add(total + cur); cur, total, seen = 0, 0, False
    if seen:
        out.add(total + cur)
    return out


def v3_fields(rec: EvidenceRecord, r: dict, source: str, review: bool = False) -> None:
    """Method v3 extraction fields (verify_claim/v6). A number phrase that is not verbatim in the abstract is dropped, and the
    number with it; values outside the closed lists are dropped. Replies of earlier templates carry none of these keys.
    A paper PubMed types as a review keeps design "review" (or "meta_analysis") even when the sentence restates one trial:
    that trial is named in reports_trial and its own paper is fetched (spec 9.1). The effect class is computed from the
    verbatim effect phrase (effect_class.py, user decision 2026-11-04); the extractor's own class counts only as "none"."""
    from hyparena.card.effect_class import effect_class
    norm = _norm(source)
    rec.design = r.get("design") if r.get("design") in V3_DESIGNS else "unknown"
    if review and rec.design not in ("review", "meta_analysis"):
        rec.design = "review"
    nq = _text(r.get("n_quote"))
    n = r.get("n_total")
    if isinstance(n, int) and n > 0 and nq and _norm(nq) in norm and (str(n) in re.sub(r"[ ,]", "", nq) + nq
                                                                       or n in words_to_numbers(nq)):
        rec.n_total, rec.n_quote = n, nq
    elif isinstance(n, int) and n > 0 and nq and _norm(nq) in norm:
        rec.n_quote = nq                                  # the phrase is real but the number is not in it: keep the phrase only
    er = _text(r.get("effect_reported"))
    rec.effect_reported = er if er and _norm(er) in norm else ""
    rec.comparison = r.get("comparison") if r.get("comparison") in ("between_groups", "within_group", "none") else "unknown"
    rec.effect_class = effect_class(rec.effect_reported, r.get("effect_class") or "")
    rec.reports_trial = _text(r.get("reports_trial"))
    if r.get("blinding") in ("double_blind", "single_blind", "assessor_blind", "open", "not_reported", "not_applicable"):
        rec.blinding = r["blinding"]                      # verify_claim/v11
    if isinstance(r.get("outcome_subjective"), bool):
        rec.outcome_subjective = r["outcome_subjective"]


RELEVANCE_TEMPLATE = ("relevance_check", "v1")


def relevance_targets(records: list, abstracts: dict) -> list[str]:
    """PMIDs whose verbatim records all came back with stance "neither": the ones a second, narrower question is asked
    about (extraction-gold-v8: the verifier gives same-kind findings stance neither and the run drops them)."""
    by = {}
    for r in records or []:
        if not isinstance(r, dict):
            continue
        pmid = str(r.get("pmid", "")).replace("PMID:", "").strip()
        a = abstracts.get(pmid)
        if a is None or not r.get("quote") or _norm(r["quote"]) not in _norm(a["title"] + " " + a["abstract"]):
            continue
        by.setdefault(pmid, []).append(r.get("stance"))
    return [p for p, st in by.items() if all(x not in ("supports", "refutes") for x in st)]


def _validate_relevance(v: dict, source: str) -> list[str]:
    r = (v or {}).get("relevance") or {}
    out = []
    if r.get("intervention") not in ("same", "same_kind", "different"):
        out.append("intervention must be same, same_kind or different.")
    if r.get("outcome") not in ("same", "same_domain", "different"):
        out.append("outcome must be same, same_domain or different.")
    if r.get("result") not in ("supports", "refutes", "none"):
        out.append("result must be supports, refutes or none.")
    if r.get("result") in ("supports", "refutes") and (not r.get("quote") or _norm(r["quote"]) not in _norm(source)):
        out.append("quote must be copied exactly from the abstract.")
    return out


def ask_relevance(client, family: str, avoid: frozenset, claim, card: HypothesisCard, pmid: str, a: dict,
                  log: Optional[list] = None) -> Optional[dict]:
    """The second question for one paper (relevance_check/v1); None when no valid answer came back."""
    p = card.pico
    source = a["title"] + " " + a["abstract"]
    variables = {"claim": claim, "claim_plain": card.claim_plain, "pmid": pmid, "title": a["title"], "abstract": a["abstract"],
                 "population": ", ".join(f"{k} {v}" for k, v in p.population.model_dump().items() if v and v != "unknown") or "unknown",
                 "intervention": "; ".join(i.label for i in p.intervention) or "unknown"}
    value, _ = ask(client, role="verify_claim", family=family, template=RELEVANCE_TEMPLATE[0], version=RELEVANCE_TEMPLATE[1],
                   variables=variables, validate=lambda v: _validate_relevance(v, source), rounds=2, avoid=avoid, log=log)
    return None if value is None or _validate_relevance(value, source) else value["relevance"]


def merge_relevance(records: list, checks: list, abstracts: dict) -> list:
    """Records with the answers of the second question applied (pure): a paper whose result is on the claim's intervention
    or one of the same kind, on the claim's outcome or its domain, with a result, gets that stance on its first record, the
    check's verbatim quote, intervention_match "class" for a same-kind intervention (an exact or related match is kept
    otherwise) and the flag relevance_check. Anything else stays as the first reader returned it."""
    out = [dict(r) if isinstance(r, dict) else r for r in records or []]
    for c in checks or []:
        pmid = str(c.get("pmid", "")).replace("PMID:", "").strip()
        if c.get("intervention") == "different" or c.get("outcome") == "different" or c.get("result") not in ("supports", "refutes"):
            continue
        a = abstracts.get(pmid)
        if a is None or not c.get("quote") or _norm(c["quote"]) not in _norm(a["title"] + " " + a["abstract"]):
            continue
        r = next((r for r in out if isinstance(r, dict) and str(r.get("pmid", "")).replace("PMID:", "").strip() == pmid), None)
        if r is None:
            continue
        r["stance"], r["quote"], r["quote_role"] = c["result"], c["quote"], "finding" if r.get("quote_role") != "background" else "background"
        if c.get("intervention") == "same_kind" and r.get("intervention_match") in (None, "", "exact", "dose_differs", "regimen_differs"):
            r["intervention_match"] = "class"
        r["flags"] = list(r.get("flags") or []) + ["relevance_check"]
    return out


def verify_claim(client, family: str, avoid: frozenset, claim, card: HypothesisCard,
                 as_of: Optional[str] = None, retmax: int = RETMAX, log: Optional[list] = None,
                 fallback: Optional[str] = None, expert_pmids: Optional[list[tuple[str, str]]] = None,
                 check_subgroups: bool = True, search: str = "keywords", template_version: str = "",
                 relevance_check: bool = False) -> ClaimVerification:
    """`fallback`: the family asked when `family`'s reply is cut off with no complete record (gemini stops in
    the middle of verbatim quotes, most likely its recitation filter)."""
    cv = ClaimVerification(id=claim.id)
    if claim.role == "alternative":
        retmax = max(retmax, ALTERNATIVE_RETMAX)          # Y decides a contrast: search it wider (spec 7, 2026-10-21)
    support, against = curated(claim, card, as_of)
    cv.evidence += support
    cv.counterevidence += against
    pmids = []
    full_text = search.endswith("+fulltext")              # sources experiment arm B (specs/sources-experiment-2026-11-07.yaml)
    search = search.replace("+fulltext", "")
    if search == "fixed":                                 # read again the papers given in expert_pmids only (no search)
        pass
    elif search in ("model", "model_population"):           # model-written queries, light guard, citation expansion (search.py)
        from hyparena.card.search import retrieve
        pmids = retrieve(client, family, avoid, claim, card, as_of, retmax, log=log, population_first=search == "model_population")
    else:
        for q in queries(claim, card):
            if q:
                pmids += [p for p in pubmed.search(q, retmax=retmax, as_of=as_of) if p not in pmids]
            if len(pmids) >= retmax:
                break
    pmids = pmids[:retmax]
    by_expert = {pmid: did for pmid, did in (expert_pmids or [])}    # sources an expert gave (spec 7a)
    pmids = list(by_expert) + [p for p in pmids if p not in by_expert]
    pmids, dropped = date_guard(pmids, as_of)
    abstracts = {p: a for p, a in pubmed.fetch(pmids).items() if a.get("abstract")}
    if full_text:                                         # PMC full text where allowed: methods and results appended; quotes are
        from hyparena.tools import pmc                    # then checked against abstract + full text
        for p_, a_ in list(abstracts.items()):
            ft = pmc.excerpt(p_)
            if ft:
                abstracts[p_] = {**a_, "abstract": a_["abstract"] + "\n\n[FULL TEXT: methods and results]\n" + ft}
    if log is not None:
        log.append({"kind": "search", "claim": claim.id, "queries": queries(claim, card), "as_of": as_of,
                    "date_guard_dropped": dropped, "expert_pmids": list(by_expert),
                    "pmids": list(abstracts), "drugage": [r.record_id for r in support + against]})
    if not abstracts:
        cv.notes = "no abstracts found"
        return cv
    p = card.pico
    negated = claim.qualifiers.get("direction", "").lower() in ("no_effect", "none", "no", "not", "no effect")
    contrast = next((a for a in card.declared_alternatives if a.id == claim.qualifiers.get("contrast")), None)
    human_healthspan = claim_endpoint(claim) == "healthspan" and \
        species_key(claim.qualifiers.get("species") or claim.object.label) == "human"
    from hyparena.card.search import ALTERNATIVE_NOTE   # 2026-11-11: a proposed alternative counts only by its own part
    variables = {"claim": claim, "negated": negated, "alternative": claim.role == "alternative",
                 "competitor": claim.note == ALTERNATIVE_NOTE,
                 "human_healthspan": human_healthspan,
                 "contrast": contrast.subject.label + " " + contrast.relation + " " + contrast.object.label if contrast else "",
                 "qualifiers": ", ".join(f"{k}: {v}" for k, v in claim.qualifiers.items()
                                         if v and v != "unknown" and k != "contrast"),
                 "endpoint": claim_endpoint(claim), "claim_plain": card.claim_plain,
                 "population": ", ".join(f"{k} {v}" for k, v in p.population.model_dump().items() if v and v != "unknown") or "unknown",
                 "intervention": "; ".join(f"{i.label} ({', '.join(x for x in (i.regimen, i.route) if x and x != UNKNOWN) or 'regimen unknown'})"
                                           for i in p.intervention) or "unknown",
                 "comparator": p.comparator.label,
                 "abstracts": [{"pmid": k, "year": a["year"], "title": a["title"], "abstract": a["abstract"],
                                "review": pubmed.is_review(a)} for k, a in abstracts.items()]}
    version = template_version or TEMPLATE[1]
    keep_no_stance = int(version.lstrip("v") or 0) >= 6     # v3 templates
    value, fam = ask(client, role="verify_claim", family=family, template=TEMPLATE[0], version=version,
                     variables=variables, validate=lambda v: _validate(v, abstracts), rounds=2, avoid=avoid, log=log,
                     parse=parse_records)
    if fallback and fallback != fam and (value is None or (value.get("truncated") and not value.get("records"))):
        value, fam = ask(client, role="verify_claim", family=fallback, template=TEMPLATE[0], version=version,
                         variables=variables, validate=lambda v: _validate(v, abstracts), rounds=2, avoid=avoid,
                         log=log, parse=parse_records)
    if relevance_check and value and value.get("records"):
        checks = [c for c in (ask_relevance(client, fam, avoid, claim, card, pmid, abstracts[pmid], log=log)
                              for pmid in relevance_targets(value["records"], abstracts)) if c]
        value = {**value, "records": merge_relevance(value["records"], checks, abstracts)}
    rejected = []
    for r in (value or {}).get("records") or []:
        if not isinstance(r, dict):
            continue
        pmid = str(r.get("pmid", "")).replace("PMID:", "").strip()
        a = abstracts.get(pmid)
        quote = r.get("quote", "")
        if a is None or _norm(quote) not in _norm(a["title"] + " " + a["abstract"]):
            rejected.append(pmid)
            continue                                      # never keep a quote that is not in the source
        review = pubmed.is_review(a)
        qm = {k: str(v) for k, v in (r.get("qualifiers_match") or {}).items() if str(v) in ("yes", "no", "n/a")}
        qm = _context_match(qm, claim, card, quote)
        qm["intervention_match"] = r.get("intervention_match") or "exact"
        prog = r.get("program") or ""
        rec = EvidenceRecord(
            source="PubMed", record_id=f"PMID:{pmid}", epistemic_type="A_text",
            study_type="review" if review else (r.get("study_type") or "other"),
            lab_or_cohort=f"PMID:{pmid}", derived_from="review" if review else "",
            species=r.get("species") or "unknown", system=r.get("system") if r.get("system") in ("ex_vivo", "in_vitro") else "",
            quote=quote, quote_role=r.get("quote_role") if r.get("quote_role") in ("finding", "background", "speculation") else "background",
            endpoint=r.get("endpoint") if r.get("endpoint") in ("lifespan", "healthspan", "biomarker", "disease", "mechanism") else "unknown",
            effect_percent=r.get("effect_percent") if isinstance(r.get("effect_percent"), (int, float)) else None,
            sex=_sex(r), strain=_text(r.get("strain")), dose=_text(r.get("dose")), age_at_start=_text(r.get("age_at_start")),
            human_rungs=[x for x in (r.get("human_rungs") or []) if x in HUMAN_RUNGS] if species_key(r.get("species") or "") == "human" else [],
            qualifiers_match=qm,
            program=ProgramInfo(name=prog) if prog in ("ITP", "CITP") else None,
            flags=[f for f in (r.get("flags") or []) if isinstance(f, str)], retrieved_at=a.get("year", ""),
            notes=f"extracted by {fam}" + (f"; source given by expert decision {by_expert[pmid]}" if pmid in by_expert else ""))
        contexts.flag(rec, a["title"] + " " + a["abstract"])
        if keep_no_stance:                                # v3: papers of one trial are one source (OHF independence groups)
            trials = set(re.findall(r"\b(NCT\d{8}|ISRCTN\d{8})\b", a["title"] + " " + a["abstract"]))
            if len(trials) == 1:
                rec.lab_or_cohort = trials.pop()
        if pubmed.is_retracted(a):
            rec.flags.append("retracted_pubmed")          # read by the v3.1 rules (section 12, point 7); v2 and v3 unchanged
        v3_fields(rec, r, a["title"] + " " + a["abstract"], review)
        # 2026-11-11: PubMed's own publication types decide the review kind and a meta-analysis; its GRADE certainty by code
        from hyparena.card.review_kind import certainty_from_abstract, design_from_pubtypes
        rec.design, rec.review_kind = design_from_pubtypes(rec.design, a.get("pubtypes", []))
        if rec.design == "meta_analysis":
            rec.certainty = certainty_from_abstract(a["abstract"])
        if rec.qualifiers_match["intervention_match"] in ("exact", "dose_differs", "regimen_differs") and not names_in_source(
                claim, card, a["title"], a["abstract"], quote):
            if subject_compounds(claim.subject.label, card):
                rec.qualifiers_match["intervention_match"] = "related_compound"   # e.g. malate quoted for a claim about citrate
                rec.notes += "; the quote and the title do not name the intervention: counted as a related compound"
            else:                                         # a programme, visit or device: another one of the same kind (2026-11-02)
                rec.qualifiers_match["intervention_match"] = "class"
                rec.notes += "; the quote and the title do not name the intervention: counted as the same class"
        stance = r.get("stance")
        need = claim_endpoint(claim)
        effect = r.get("effect") if r.get("effect") in ("increase", "decrease", "no_effect") else "unknown"
        rec.effect = effect
        if need == "lifespan" and rec.endpoint == "lifespan" and rec.quote_role == "finding" and effect != "unknown":
            # the stance of a lifespan finding follows from its direction, as for DrugAge (code, not the extractor)
            coded = "supports" if effect == lifespan_wanted(claim) else "refutes"
            if coded != stance:
                rec.notes += f"; stance set from the effect direction ({effect}); the extractor said {stance}"
            stance = coded
        mismatched = [k for k, v in qm.items() if v == "no" and k != "intervention_match"]
        if stance in ("supports", "refutes") and mismatched and set(mismatched) <= set(claim.inherited_from_pico):
            # a mismatch only on a value inherited from PICO: a soft refusal, not a status (spec 7)
            cv.refusals.append(Refusal(type="inherited_mismatch", record_id=rec.record_id, quote=quote,
                                       notes=f"{', '.join(mismatched)} inherited from PICO; the record is about {rec.species}"))
        elif stance == "supports":
            cv.evidence.append(rec)
        elif stance == "refutes":
            cv.counterevidence.append(rec)
        elif need and rec.endpoint not in ("unknown", need) and rec.quote_role == "finding":
            cv.refusals.append(Refusal(type="endpoint_mismatch", record_id=rec.record_id, quote=quote,
                                       notes=f"measures {rec.endpoint}, the claim is about {need}"))
        elif keep_no_stance and rec.quote_role == "finding":
            cv.no_stance.append(rec)                      # v3: kept, not scored (sensitivity analysis only)
    mark_subgroup(cv.evidence, cv.counterevidence)
    if check_subgroups:
        check_subgroup(client, family, avoid, claim, card, cv, log=log, fallback=fallback)
    if rejected:
        cv.notes = (cv.notes + "; " if cv.notes else "") + f"quotes not found verbatim, dropped: {', '.join(rejected)}"
    if (value or {}).get("truncated"):
        cv.notes = (cv.notes + "; " if cv.notes else "") + "reply cut off: only its complete records were kept"
    return cv


def check_subgroup(client, family: str, avoid: frozenset, claim, card: HypothesisCard, cv: ClaimVerification,
                   log: Optional[list] = None, fallback: Optional[str] = None) -> None:
    """Spec 7, "Subgroup-only support" (2026-10-21): when all the support is subgroup-only and no null or negative
    finding was found, one targeted query asks the same papers' abstracts, and the ClinicalTrials.gov record of a
    registered trial, for the whole-sample result on the primary outcome. Null or negative → counterevidence
    (the claim becomes contested), positive → evidence (supported); nothing → the rules leave it unverified with
    flag `subgroup_unchecked`. The subgroup records stay in evidence."""
    support = [r for r in cv.evidence if admissible(r, claim)]
    if not subgroup_only(support) or any(admissible(r, claim) for r in cv.counterevidence):
        return
    pmids = list(dict.fromkeys(r.record_id.replace("PMID:", "") for r in support if r.record_id.startswith("PMID:")))
    abstracts = {p: a for p, a in pubmed.fetch(pmids).items() if a.get("abstract")}
    sources, of_pmid = [], {}
    for p, a in abstracts.items():
        sources.append({"id": f"PMID:{p}", "kind": f"abstract, {a.get('year', '')}",
                        "text": f"{a['title']}\n{a['abstract']}"})
        for nct in dict.fromkeys(NCT.findall(a["abstract"])):
            text = trials.registry_text(nct)
            if text:
                sources.append({"id": nct, "kind": f"ClinicalTrials.gov record of PMID {p}", "text": text})
                of_pmid[nct] = p
    if log is not None:
        log.append({"kind": "subgroup_check", "claim": claim.id, "sources": [x["id"] for x in sources]})
    if not sources:
        return
    texts = {x["id"]: x["text"] for x in sources}

    def source_of(r: dict) -> str:
        """The source id as given ("[PMID:1]", "PMID 1", "1" are read as "PMID:1"), else the study's abstract."""
        src = re.sub(r"^PMID\s*:?\s*", "PMID:", str(r.get("source", "")).strip(" []"), flags=re.I)
        src = src if src in texts else f"PMID:{src}"
        return src if src in texts else f"PMID:{str(r.get('pmid', '')).replace('PMID:', '').strip()}"

    def validate(v: dict) -> list[str]:
        problems = []
        for i, r in enumerate(v.get("results") or []):
            if not isinstance(r, dict):
                problems.append(f"result {i}: not an object")
            elif r.get("quote") and source_of(r) not in texts:
                problems.append(f"result {i}: source {r.get('source')} is not one of the given sources")
            elif r.get("quote") and _norm(r["quote"]) not in _norm(texts[source_of(r)]):
                problems.append(f"result {i}: the quote is not copied verbatim from {r.get('source')}")
        return problems
    variables = {"claim": claim, "claim_plain": card.claim_plain, "sources": sources,
                 "subgroup": [{"record_id": r.record_id, "quote": r.quote} for r in support]}
    value, fam = ask(client, role="verify_claim", family=family, template=SUBGROUP_TEMPLATE[0],
                     version=SUBGROUP_TEMPLATE[1], variables=variables, validate=validate, rounds=2, avoid=avoid, log=log)
    if value is None and fallback and fallback != family:
        value, fam = ask(client, role="verify_claim", family=fallback, template=SUBGROUP_TEMPLATE[0],
                         version=SUBGROUP_TEMPLATE[1], variables=variables, validate=validate, rounds=2, avoid=avoid, log=log)
    found = []
    for r in (value or {}).get("results") or []:
        if not isinstance(r, dict) or r.get("result") not in ("positive", "null", "negative"):
            continue
        src, quote = source_of(r), r.get("quote", "")
        if src not in texts or not quote or _norm(quote) not in _norm(texts[src]):
            continue                                      # never keep a quote that is not in the source
        pmid = of_pmid.get(src) or src.replace("PMID:", "")
        base = next((x for x in support if x.record_id == f"PMID:{pmid}"), support[0])
        rec = base.model_copy(deep=True, update={
            "source": "ClinicalTrials.gov" if src in of_pmid else "PubMed", "record_id": src,
            "lab_or_cohort": f"PMID:{pmid}", "linked_pmid": pmid if src in of_pmid else "", "quote": quote,
            "quote_role": "finding", "sex": "unknown", "effect_percent": None, "effect": "unknown",
            "endpoint": r.get("endpoint") if r.get("endpoint") in ("lifespan", "healthspan", "biomarker", "disease",
                                                                    "mechanism") else base.endpoint,
            "human_rungs": [x for x in (r.get("human_rungs") or []) if x in HUMAN_RUNGS] if base.human_rungs else [],
            "flags": [f for f in base.flags if f not in ("subgroup_only", "secondary_outcome")],
            "notes": f"whole-sample primary outcome ({r['result']}), found by the subgroup check; extracted by {fam}"})
        rec.qualifiers_match.pop("sex", None)
        if rec.endpoint == "lifespan":
            wanted = lifespan_wanted(claim)
            opposite = {"increase": "decrease", "decrease": "increase"}.get(wanted, "unknown")
            rec.effect = {"positive": wanted, "null": "no_effect", "negative": opposite}[r["result"]] or "unknown"
        (cv.evidence if r["result"] == "positive" else cv.counterevidence).append(rec)
        found.append(f"{src} {r['result']}")
    cv.notes = (cv.notes + "; " if cv.notes else "") + \
        f"subgroup check: {', '.join(found) if found else 'no whole-sample primary result found'}"


def _sex(r: dict) -> str:
    sex = str(r.get("sex") or "").lower()
    if sex in ("male", "female", "both", "unknown"):
        return sex
    sexes = {x for x in (r.get("sexes") or []) if x in ("male", "female")}       # the v4 reply form
    return "both" if len(sexes) == 2 else next(iter(sexes), "unknown")


def _text(v) -> str:
    return str(v).strip() if isinstance(v, (str, int, float)) and str(v).strip().lower() not in ("", "unknown", "none", "n/a") else ""


def analog_probes(card: HypothesisCard) -> list[Claim]:
    """Claims the verifier adds in its own layer (spec 4, 8): when an interventional hypothesis is about
    humans, the same intervention's lifespan and healthspan effect in mice, which can set the effect level
    below the human rungs."""
    out = card.outcome_claim
    if card.hypothesis_type != "interventional" or not card.pico.intervention or out is None:
        return []
    human = any(w in (out.object.label + " " + card.pico.population.label + " " + (card.pico.population.taxon or "")).lower()
                for w in ("human", "adult", "people", "patient", "9606"))
    if not human:
        return []
    label = " + ".join(i.label for i in card.pico.intervention)
    return [Claim(id="an1", subject=Entity(label=label), relation="extends_lifespan_in", object=Entity(label="mouse"),
                  qualifiers={"species": "mouse"}, role="analog", note="added by the verifier"),
            Claim(id="an2", subject=Entity(label=label), relation="improves_healthspan_in", object=Entity(label="mouse"),
                  qualifiers={"species": "mouse"}, role="analog", note="added by the verifier")]


def verify(client, families: list[str], writer: str, card: HypothesisCard, as_of: Optional[str] = None,
           log: Optional[list] = None, map_fn=map,
           expert_sources: Optional[dict[str, list[tuple[str, str]]]] = None,
           fallback_families: Optional[list[str]] = None, disease_restore: frozenset = frozenset(),
           search: str = "keywords", template_version: str = "", probes: bool = True) -> Verification:
    """All declared claims, the rejected alternatives of a contrast (checked like claims, spec 7), plus analog
    probes; the verifier's family is never the writer's (its records feed the ranking)."""
    log = log if log is not None else []                  # its search entries give searched_pmids
    allowed = [f for f in families if f != writer] or families
    # mouse probes are method v2 (effect level below the human rungs); method v3 does not use them (H49 walkthrough 2026-11-11)
    probes = analog_probes(card) if probes else []
    claims = card.claims + card.rejected_alternatives + probes
    # the family asked when the first returns nothing: the next verifier, else another family of the config (a
    # provider content filter blocks some abstracts: DeepSeek on PMID 22587563, 2026-10-21)
    spare = [f for f in (fallback_families or []) if f != writer and f not in allowed]

    def fallback(i):
        nxt = allowed[(i + 1) % len(allowed)]
        return nxt if nxt != allowed[i % len(allowed)] else (spare[0] if spare else nxt)
    tasks = [(c, allowed[i % len(allowed)], fallback(i)) for i, c in enumerate(claims)]
    expert_sources = expert_sources or {}
    cvs = list(map_fn(lambda t: verify_claim(client, t[1], frozenset({writer}), t[0], card, as_of, log=log,
                                             fallback=t[2], expert_pmids=expert_sources.get(t[0].id), search=search,
                                             template_version=template_version), tasks))
    added = {c.id for c in probes}
    for cv, c in zip(cvs, claims):
        if cv.id in added:
            cv.claim = c
    searched = [p for e in (log or []) if e.get("kind") == "search" for p in e.get("pmids", [])]
    ver = Verification(card_id=card.id, claims=cvs, searched_pmids=list(dict.fromkeys(searched)))
    return add_strain_analogs(card, add_disease_analogs(card, ver, disease_restore))

"""Paper-level functional outcome retention for empty outcome slots (method v3.13).

When a hypothesis's outcome slot has no records (so novelty_v34 would assign new_link or new_combination),
earlier-link abstracts already retrieved by the pipeline may still report directly measured functional or
clinical outcomes under the same or closely related intervention (e.g. wound healing area in a paper read for
a mechanism step). This module extracts up to two verified functional outcomes per earlier-link abstract
(carrying intervention_tested, same_intervention_family, endpoint_role, same_outcome_domain, and a verbatim
excerpt checked by code) and supplies them to novelty_v34 without changing evidence balance weights.
"""
from __future__ import annotations

import json
import re
from typing import Optional

from hyparena.card.models import ClaimVerification, HypothesisCard
from hyparena.llm.prompts import render
from hyparena.reading.verifier import _norm, parse_records

TEMPLATE_VERSION = "v2"
QUALIFYING_ROLES = ("human_clinical_or_function", "animal_behavioral_or_function")
QUALIFYING_FAMILIES = ("exact", "class_or_regimen")
QUALIFYING_DOMAINS = ("same", "adjacent")


def repair_measure(measure: str, excerpt: str, full_text: str) -> Optional[str]:
    """Recover a verbatim measure span inside `excerpt` when one extra leading word was copied from `full_text`."""
    words = (measure or "").split()
    if len(words) < 3 or not words[0].isalpha() or words[0].lower() in {"no", "not", "without"}:
        return None
    whole = r"(?<!\w)" + re.escape(_norm(measure)) + r"(?!\w)"
    if not re.search(whole, _norm(full_text)):
        return None
    suffix = re.findall(r"\w+", " ".join(words[1:]).lower())
    generic = {"the", "a", "an", "of", "in", "by", "and", "or", "rate", "score", "mean", "percent", "change"}
    if len([w for w in suffix if w not in generic]) < 2:
        return None
    pattern = r"(?<!\w)" + r"\s+".join(re.escape(w) for w in words[1:]) + r"(?!\w)"
    match = re.search(pattern, excerpt, re.IGNORECASE)
    return match.group() if match else None


def _parse_json(text: str) -> Optional[dict]:
    if not text:
        return None
    val = parse_records(text)
    if isinstance(val, dict):
        return val
    m = re.search(r"\{.*\}", text, re.S)
    if m:
        try:
            obj = json.loads(m.group(0))
            return obj if isinstance(obj, dict) else None
        except Exception:
            return None
    return None


def validate(value: Optional[dict], pmid: str, paper: dict) -> tuple[list[dict], list[str]]:
    """Verify source_pmid, contiguous verbatim excerpt, and verbatim measure inside excerpt."""
    if not isinstance(value, dict):
        return [], ["unparsed"]
    items = value.get("paper_outcomes")
    if not isinstance(items, list):
        return [], ["missing_list"]
    full = f"{paper.get('title') or ''}\n{paper.get('abstract') or ''}"
    norm_full = _norm(full)
    ok: list[dict] = []
    issues: list[str] = []
    seen: set[tuple[str, str]] = set()
    for it in items[:2]:
        if not isinstance(it, dict):
            issues.append("bad_item")
            continue
        sp = str(it.get("source_pmid") or "").strip().removeprefix("PMID:")
        ex = str(it.get("excerpt") or "").strip()
        ms = str(it.get("measure") or "").strip()
        if sp != str(pmid):
            issues.append("wrong_pmid")
            continue
        if not ex or _norm(ex) not in norm_full:
            issues.append("unverified_excerpt")
            continue
        if not ms or _norm(ms) not in _norm(ex):
            fixed = repair_measure(ms, ex, full)
            if not fixed:
                issues.append("measure_not_in_excerpt")
                continue
            ms = fixed
        key = (_norm(ms), _norm(ex))
        if key in seen:
            issues.append("duplicate")
            continue
        seen.add(key)
        ok.append({
            "source_pmid": str(pmid),
            "intervention_tested": str(it.get("intervention_tested") or ""),
            "same_intervention_family": str(it.get("same_intervention_family") or "different"),
            "endpoint_role": str(it.get("endpoint_role") or "physiological_or_marker"),
            "same_outcome_domain": str(it.get("same_outcome_domain") or "different"),
            "species": str(it.get("species") or "unknown"),
            "measure": ms,
            "excerpt": ex,
        })
    return ok, issues


def qualifying(paper_outcomes: Optional[list[dict]]) -> list[dict]:
    """Keep only verified paper-own functional outcomes on the same/related intervention family and outcome domain."""
    if not paper_outcomes:
        return []
    return [
        o for o in paper_outcomes
        if isinstance(o, dict)
        and o.get("endpoint_role") in QUALIFYING_ROLES
        and o.get("same_intervention_family") in QUALIFYING_FAMILIES
        and o.get("same_outcome_domain") in QUALIFYING_DOMAINS
        and o.get("source_pmid")
        and o.get("excerpt")
    ]


def novelty_from_outcomes(base_level: Optional[str], paper_outcomes: Optional[list[dict]]) -> tuple[Optional[str], Optional[str]]:
    """When `base_level` is new_link or new_combination (empty outcome slot), check whether verified earlier-link
    functional outcomes already tested the same intervention family and outcome domain.
    Returns (level, source_pmid)."""
    if base_level not in ("new_link", "new_combination"):
        return base_level, None
    hits = qualifying(paper_outcomes)
    if not hits:
        return base_level, None
    exact_human = [o for o in hits if o.get("same_intervention_family") == "exact" and o.get("species") == "human"]
    if exact_human:
        return "new_context", str(exact_human[0]["source_pmid"])
    exact_any = [o for o in hits if o.get("same_intervention_family") == "exact"]
    if exact_any:
        return "translation", str(exact_any[0]["source_pmid"])
    return "analog", str(hits[0]["source_pmid"])


def extract(
    client,
    card: HypothesisCard,
    cvs: list[ClaimVerification],
    abstracts: dict[str, dict],
    *,
    avoid: frozenset[str] = frozenset(),
    family: Optional[str] = None,
    log: Optional[list] = None,
    max_papers: int = 5,
) -> list[dict]:
    """Run paper_outcomes/v2 on up to `max_papers` unique PMIDs from earlier (non-outcome) links."""
    from hyparena.novelty import novelty_v34 as nv

    _, out_ids = nv.slots(card)
    out_set = set(out_ids)
    pmids: list[str] = []
    for cv in cvs:
        if cv.id in out_set:
            continue
        for rec in cv.evidence + cv.counterevidence:
            pm = rec.record_id.removeprefix("PMID:")
            if pm.isdigit() and pm in abstracts and pm not in pmids:
                pmids.append(pm)
    pmids = pmids[:max_papers]
    if not pmids:
        return []

    chosen_family = family
    if not chosen_family:
        fams = [f for f in getattr(client, "families", lambda: [])() if f not in avoid] if callable(getattr(client, "families", None)) else []
        chosen_family = "deepseek" if "deepseek" in fams else (fams[0] if fams else None)
    if not chosen_family:
        return []

    intervention = "; ".join(f"{i.label} ({i.type})" for i in card.pico.intervention)
    population = card.pico.population.label
    outcome = card.pico.outcome.metric or (card.outcome_claim.object.label if card.outcome_claim else "")

    collected: list[dict] = []
    for pm in pmids:
        paper = abstracts[pm]
        prompt = render(
            "paper_outcomes",
            TEMPLATE_VERSION,
            intervention=intervention,
            population=population,
            outcome=outcome,
            pmid=pm,
            year=paper.get("year") or "",
            title=paper.get("title") or "",
            abstract=paper.get("abstract") or "",
        )
        reply = client.call(role="verify_claim", family=chosen_family, prompt=prompt)
        rows, issues = validate(_parse_json(reply.text), pm, paper)
        if log is not None:
            log.append({
                "kind": "llm",
                "template": f"paper_outcomes/{TEMPLATE_VERSION}",
                "role": "verify_claim",
                "family": chosen_family,
                "pmid": pm,
                "accepted": len(rows),
                "issues": issues,
                "tokens_in": getattr(reply, "tokens_in", 0),
                "tokens_out": getattr(reply, "tokens_out", 0),
                "seconds": getattr(reply, "seconds", 0.0),
                "error": getattr(reply, "error", None),
            })
        collected.extend(rows)
    return collected

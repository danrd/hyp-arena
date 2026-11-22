"""Channel B: technical implementation readiness for non-compound interventions (method v3.13).

For compound interventions, regulatory status comes from ChEMBL and ClinicalTrials.gov up to T.
For non-compound interventions (devices, procedures, gene/cell perturbations, exercise, diet), this module
runs one focused reader call over the pre-cutoff abstracts already retrieved for the hypothesis and requires
a code-verified verbatim quote demonstrating the limiting operation:
  - demonstrated -> 1.0 (reason: impl_demonstrated)
  - conditional  -> 0.5 (reason: impl_conditional)
  - missing      -> 0.0 (reason: impl_missing)
Any supported status whose quote fails verbatim verification is automatically downgraded to missing (0.0).
"""
from __future__ import annotations

import json
import re
from typing import Optional

from hyparena.card.models import ClaimVerification, HypothesisCard
from hyparena.llm.prompts import render
from hyparena.reading.verifier import _norm, parse_records

TEMPLATE_VERSION = "v1"
STATUS_SCORE = {"demonstrated": 1.0, "conditional": 0.5, "missing": 0.0}
STATUS_REASON = {"demonstrated": "impl_demonstrated", "conditional": "impl_conditional", "missing": "impl_missing"}


def is_non_drug(card: HypothesisCard) -> bool:
    """True when the card names interventions and at least one is not a compound (and none are blank/unspecified)."""
    interventions = card.pico.intervention
    if not interventions or any(i.type == "unspecified" or i.label.strip().casefold() in {"", "unknown"} for i in interventions):
        return False
    if any(i.type == "other" for i in interventions):
        return False
    return any(i.type != "compound" for i in interventions)


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


def validate(value: Optional[dict], supplied: dict[str, dict]) -> dict:
    """Verify implementation_status and require a contiguous verbatim quote for demonstrated/conditional."""
    if not isinstance(value, dict):
        return {
            "limiting_means": "", "limiting_operation": "", "raw_status": "error",
            "verified_status": "missing", "evidence_pmid": "", "evidence_quote": "",
            "quote_ok": False, "issue": "unparsed", "gap": "",
        }
    raw_st = str(value.get("implementation_status") or "missing").strip().lower()
    if raw_st not in STATUS_SCORE:
        raw_st = "missing"
    pm = str(value.get("evidence_pmid") or "").strip().removeprefix("PMID:")
    qt = str(value.get("evidence_quote") or "").strip()
    quote_ok = False
    issue = ""
    if raw_st in ("demonstrated", "conditional"):
        if pm in supplied:
            full = f"{supplied[pm].get('title') or ''}\n{supplied[pm].get('abstract') or ''}"
            if qt and _norm(qt) in _norm(full):
                quote_ok = True
            else:
                issue = "unverified_quote"
        else:
            issue = "invalid_pmid"
        verified = raw_st if quote_ok else "missing"
    else:
        verified = "missing"
    return {
        "limiting_means": str(value.get("limiting_means") or ""),
        "limiting_operation": str(value.get("limiting_operation") or ""),
        "raw_status": raw_st,
        "verified_status": verified,
        "evidence_pmid": pm if quote_ok else "",
        "evidence_quote": qt if quote_ok else "",
        "quote_ok": quote_ok,
        "issue": issue,
        "gap": str(value.get("gap") or ""),
    }


def assess(
    client,
    card: HypothesisCard,
    cvs: list[ClaimVerification],
    abstracts: dict[str, dict],
    experiment_text: str = "",
    *,
    avoid: frozenset[str] = frozenset(),
    family: Optional[str] = None,
    log: Optional[list] = None,
    max_papers: int = 8,
) -> dict:
    """Run one Channel B readiness check over up to `max_papers` already-retrieved abstracts."""
    pmids: list[str] = []
    for cv in cvs:
        for rec in cv.evidence + cv.counterevidence:
            pm = rec.record_id.removeprefix("PMID:")
            if pm.isdigit() and pm in abstracts and pm not in pmids:
                pmids.append(pm)
    supplied = {pm: abstracts[pm] for pm in pmids[:max_papers]}
    if not supplied:
        return {
            "limiting_means": "; ".join(i.label for i in card.pico.intervention),
            "limiting_operation": "", "raw_status": "missing", "verified_status": "missing",
            "evidence_pmid": "", "evidence_quote": "", "quote_ok": False,
            "issue": "no_abstracts", "gap": "No pre-cutoff abstracts available.",
        }

    chosen_family = family
    if not chosen_family:
        fams = [f for f in getattr(client, "families", lambda: [])() if f not in avoid] if callable(getattr(client, "families", None)) else []
        chosen_family = "deepseek" if "deepseek" in fams else (fams[0] if fams else None)
    if not chosen_family:
        return {
            "limiting_means": "", "limiting_operation": "", "raw_status": "missing",
            "verified_status": "missing", "evidence_pmid": "", "evidence_quote": "",
            "quote_ok": False, "issue": "no_family", "gap": "",
        }

    abs_block = "\n\n".join(
        f"[PMID {pm} ({p.get('year') or ''})]\nTitle: {p.get('title') or ''}\nAbstract: {p.get('abstract') or ''}"
        for pm, p in supplied.items()
    )
    de = card.decisive_experiment
    exp_summary = (
        f"design={de.design}, control={de.control}, endpoint={de.endpoint}, "
        f"duration={de.duration_class}, n={de.n_planned}"
    )
    prompt = render(
        "implementation_readiness",
        TEMPLATE_VERSION,
        claim=card.claim_plain,
        interventions="; ".join(f"{i.label} (type={i.type})" for i in card.pico.intervention),
        system=de.system,
        exp_summary=exp_summary,
        exp_text=(experiment_text or "")[:1500],
        abstracts_block=abs_block,
    )
    reply = client.call(role="verify_claim", family=chosen_family, prompt=prompt)
    checked = validate(_parse_json(reply.text), supplied)
    if log is not None:
        log.append({
            "kind": "llm",
            "template": f"implementation_readiness/{TEMPLATE_VERSION}",
            "role": "verify_claim",
            "family": chosen_family,
            "verified_status": checked["verified_status"],
            "quote_ok": checked["quote_ok"],
            "issue": checked["issue"],
            "tokens_in": getattr(reply, "tokens_in", 0),
            "tokens_out": getattr(reply, "tokens_out", 0),
            "seconds": getattr(reply, "seconds", 0.0),
            "error": getattr(reply, "error", None),
        })
    return checked

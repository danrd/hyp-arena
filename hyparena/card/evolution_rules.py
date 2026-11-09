"""Code checks of the rules every improved version keeps (method-v3-manual.md section 11, user decision 2026-11-09), and the
decomposition of a version's score change into the hypothesis part and the experiment part (backlog 2026-11-09).

    check(parent, child, mode, ...) -> {"rules": [...], "violations": [...], "warnings": [...]}
    decompose(parent_axes, child_axes) -> {profile: {"total", "hypothesis", "experiment"}}

`parent` and `child` are (card, verification claims, search logs {claim id: PMIDs}) as the saved runs hold them. Rules 1, 2, 4
and 5 compare records of the same paper across the two versions; rule 3 compares link texts; rule 6 counts PubMed records on a
new link's own subject and object (network, free; skipped when `pubmed` is False); rule 7 counts arms and invasive or
specialised measures named in the experiment text; rule 8 needs the profile scores.
"""
from __future__ import annotations

import re
from typing import Callable, Optional

from hyparena.card import rules_v3 as r3
from hyparena.card import rules_v32 as r32
from hyparena.card.models import Claim, ClaimVerification, HypothesisCard

STRICT_MODES = ("tune", "directed")          # rule 3 is a violation there; free mode reports the change
ABSENCE_THRESHOLD = 5                        # rule 6: proposed in specs/directed-evolution-2026-11-09.yaml, fixed before a pilot
INVASIVE = re.compile(r"\b(biops\w*|MRI|fMRI|PET|CT scan|computed tomography|imaging|ultrasound|HD-?sEMG|EMG|electromyograph\w*|"
                      r"lumbar puncture|CSF|cerebrospinal|muscle sample\w*|tissue sample\w*|endoscop\w*|clamp|tracer|isotope\w*)\b", re.I)
ARMS = re.compile(r"\b(\d)\s*[x×]\s*(\d)(?:\s*[x×]\s*(\d))?\b|\b(\w+)[- ]arm(ed)?\b", re.I)
NUMBER_WORDS = {"two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "2": 2, "3": 3, "4": 4, "5": 5, "6": 6}
SCOPE_RANK = {"local": 0, "organ": 1, "hallmark": 2}
MAX_LABEL_WORDS = 4                          # rule 6: longer labels are not counted (reported as 'label too long')
STOP = {"of", "the", "and", "or", "in", "to", "a", "an", "with", "by", "for", "on", "at", "from", "via", "as"}


def _content(label: str) -> list[str]:
    return [w for w in re.findall(r"[A-Za-z0-9-]+", label or "") if w.lower() not in STOP]


def _text(c: Claim) -> str:
    q = ";".join(f"{k}={v}" for k, v in sorted(c.qualifiers.items()) if v)
    return f"{c.subject.label}|{c.relation}|{c.object.label}|{q}".lower()


def _pmid(rec) -> str:
    return rec.record_id.replace("PMID:", "")


def _records(card: HypothesisCard, cvs: list[ClaimVerification]) -> dict[str, list[tuple[str, str, object, Claim]]]:
    """PMID -> [(claim id, side, record, claim)] of counting records (weight > 0 under the current method)."""
    cl = {c.id: c for c in card.claims}
    out: dict[str, list] = {}
    for cv in cvs:
        k = cl.get(cv.id)
        if k is None:
            continue
        for side, lst in (("for", cv.evidence), ("against", cv.counterevidence)):
            for r in lst:
                if r32.current_weight(r, k, side == "against") > 0:
                    out.setdefault(_pmid(r), []).append((cv.id, side, r, k))
    return out


def _supported(card: HypothesisCard, cvs: list[ClaimVerification], alts: Optional[dict] = None) -> tuple[r32.V32Result, list[Claim]]:
    e = r32.evaluate(card, cvs, alts or {}, v36=True)
    return e, [c for c in r3.chain(card) if c.id in e.links and e.links[c.id][0] > 0.5]


def pubmed_pair_count(subject: str, obj: str, as_of: str, get: Optional[Callable] = None) -> Optional[int]:
    """Rule 6: PubMed records with the link's subject AND object (as labelled on the card) published on or before T. Built by
    code from the two labels only; a third term is never added."""
    if not subject or not obj:
        return None
    if max(len(_content(subject)), len(_content(obj))) > MAX_LABEL_WORDS:
        return None          # a long label is itself a conjunction of terms: no count rather than a false 0
    term = f"({subject}) AND ({obj})"   # PubMed's own term mapping; no field tags, no quotes, no third term
    params = {"db": "pubmed", "term": term, "retmode": "json", "tool": "hyp-arena", "datetype": "pdat",
              "mindate": "1800/01/01", "maxdate": (as_of or "3000-01-01").replace("-", "/")}
    try:
        if get is None:
            import httpx
            r = httpx.get("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi", params=params, timeout=60)
            return int(r.json()["esearchresult"]["count"])
        return int(get(params))
    except Exception:
        return None


def experiment_cost(text: str) -> dict:
    """Rule 7: the number of arms (largest factorial product or 'N-arm' found) and the invasive or specialised measures named."""
    arms = 0
    for m in ARMS.finditer(text or ""):
        if m.group(1):
            arms = max(arms, int(m.group(1)) * int(m.group(2)) * (int(m.group(3)) if m.group(3) else 1))
        elif m.group(4) and m.group(4).lower() in NUMBER_WORDS:
            arms = max(arms, NUMBER_WORDS[m.group(4).lower()])
    measures = sorted({m.group(1).lower() for m in INVASIVE.finditer(text or "")})
    return {"arms": arms or None, "invasive_or_specialised": measures}


def check(parent: tuple, child: tuple, mode: str = "tune", as_of: str = "", child_experiment_text: str = "",
          parent_alts: Optional[dict] = None, child_alts: Optional[dict] = None, scores: Optional[dict] = None,
          room_after: Optional[dict] = None, pubmed: bool = False, get: Optional[Callable] = None) -> dict:
    pc, pcv, plogs = parent
    cc, ccv, clogs = child
    pr, cr = _records(pc, pcv), _records(cc, ccv)
    ep, psup = _supported(pc, pcv, parent_alts)
    ec, csup = _supported(cc, ccv, child_alts)
    read_in_child = {p for v in (clogs or {}).values() for p in v}
    ctexts = {_text(c): c for c in r3.chain(cc)}
    rules = []

    # 1. records only from reading the version: a parent record against that is gone is listed with the reason
    gone = []
    for p, rows in pr.items():
        if not any(side == "against" for _, side, _, _ in rows):
            continue
        if any(side == "against" for _, side, _, _ in cr.get(p, [])):
            continue
        reason = ("re-read, now for" if any(side == "for" for _, side, _, _ in cr.get(p, [])) else
                  "re-read, no record" if p in read_in_child else "not read in the version")
        gone.append({"pmid": p, "parent_links": sorted({cid for cid, s, _, _ in rows if s == "against"}), "reason": reason})
    rules.append({"rule": 1, "name": "records only from reading the version", "gone_against": gone,
                  "violation": any(g["reason"] == "not read in the version" for g in gone)})

    # 2. records are not moved between links: report papers that count on another link type than in the parent
    moved = []
    for p, rows in cr.items():
        before = {k.link for _, _, _, k in pr.get(p, [])}
        after = {k.link for _, _, _, k in rows}
        if before and after and not (after & before):
            moved.append({"pmid": p, "parent_links": sorted(before), "version_links": sorted(after)})
    rules.append({"rule": 2, "name": "records not moved between links", "moved": moved, "violation": False,
                  "note": "in the pipeline a record comes from reading, so a move is reported, not a violation; a writer-supplied move is"})

    # 3. supported links kept
    lost = [{"id": c.id, "text": f"{c.subject.label} — {c.relation} — {c.object.label}"} for c in psup if _text(c) not in ctexts]
    rules.append({"rule": 3, "name": "supported links kept", "changed": lost, "violation": bool(lost) and mode in STRICT_MODES})

    # 4. scope not raised by rewording: a rise to a hallmark must come from a kept link
    w_up = SCOPE_RANK.get(ec.scope, 0) > SCOPE_RANK.get(ep.scope, 0)
    hallmark_links = [c for c in csup if c.object.hallmark or c.subject.hallmark]
    from_rewritten = [c.id for c in hallmark_links if _text(c) not in {_text(x) for x in r3.chain(pc)}]
    rules.append({"rule": 4, "name": "scope not raised by rewording", "W": [ep.scope, ec.scope],
                  "hallmark_from_rewritten_links": from_rewritten if w_up else [],
                  "violation": w_up and ec.scope == "hallmark" and bool(from_rewritten) and len(from_rewritten) == len(hallmark_links)})

    # 5. narrowing to the found papers: the same paper's record moves from adjacent (or class) to exact
    lifted = []
    for p, rows in cr.items():
        lv_before = {r3.context_level(r) for _, s, r, _ in pr.get(p, []) if s == "for"}
        lv_after = {r3.context_level(r) for _, s, r, _ in rows if s == "for"}
        if "exact" in lv_after and lv_before and "exact" not in lv_before:
            lifted.append({"pmid": p, "before": sorted(x for x in lv_before if x), "links": sorted({k.id for _, _, _, k in rows})})
    rules.append({"rule": 5, "name": "narrowing to the found papers shown", "fitted_to_found_papers": lifted, "violation": False})

    # 6. novelty by absence counted by code on the new link's own subject and object
    from hyparena.card import novelty_v34 as nv
    levels = nv.link_levels(cc, ccv)
    new_links = [c for c in r3.chain(cc) if levels.get(c.id) == "new_link" and _text(c) not in {_text(x) for x in r3.chain(pc)}]
    counts = []
    for c in new_links:
        n = pubmed_pair_count(c.subject.label, c.object.label, as_of, get) if pubmed else None
        too_long = max(len(_content(c.subject.label)), len(_content(c.object.label))) > MAX_LABEL_WORDS
        counts.append({"id": c.id, "subject": c.subject.label, "object": c.object.label, "pubmed_before_T": n,
                       "new": None if n is None else n < ABSENCE_THRESHOLD, "label_too_long": too_long})
    rules.append({"rule": 6, "name": "novelty by absence counted by code", "new_links": counts,
                  "violation": any(x["new"] is False for x in counts)})

    # 7. a bigger experiment costs feasibility (shown next to I until feasibility counts it)
    cost = experiment_cost(child_experiment_text)
    rules.append({"rule": 7, "name": "experiment cost shown", "I": [round(ep.I, 3), round(ec.I, 3)], **cost, "violation": False})

    # 8. a rise in every profile at once with P = 1 and no room left is a warning
    warn8 = False
    if scores:
        ups = [b is not None and a is not None and b > a for a, b in scores.values()]
        warn8 = bool(ups) and all(ups) and ec.P >= 0.999 and (room_after is None or max(room_after.values() or [0]) < 0.02)
    rules.append({"rule": 8, "name": "rise in every profile is a warning", "warning": warn8, "violation": False})

    return {"rules": rules, "violations": [r["rule"] for r in rules if r.get("violation")],
            "warnings": [r["rule"] for r in rules if r.get("warning")] + ([5] if lifted else []) + ([1] if gone else [])}


HYPOTHESIS_PART = ("P", "scope", "support_share", "chain_state", "N", "best_design_outcome", "independent_outcome",
                   "trend_pubmed", "ai_role", "against_share", "leverage", "W_potential", "literature_density")
EXPERIMENT_PART = ("I", "headroom_I", "feasibility", "endpoint_clinical")


def _mix(base: tuple[dict, dict], src: tuple[dict, dict], keys: tuple) -> tuple[dict, dict]:
    v3, ext = dict(base[0]), dict(base[1])
    for k in keys:
        if k in src[0]:
            v3[k] = src[0][k]
        if k in src[1]:
            ext[k] = src[1][k]
    return v3, ext


def decompose(parent_axes: tuple[dict, dict], child_axes: tuple[dict, dict], K: int = 10000) -> dict:
    """The score change of a version under each profile split into the hypothesis part (what is known and how new) and the
    experiment part (how good the test is), by the symmetric (Shapley) split of the two swaps; the parts sum to the total.
    Unknown values are drawn per entry, so a part below about 0.005 (K = 10 000) is noise."""
    from hyparena.card import improvements as imp
    entries = {"parent": parent_axes, "child": child_axes,
               "hyp_only": _mix(parent_axes, child_axes, HYPOTHESIS_PART),
               "exp_only": _mix(parent_axes, child_axes, EXPERIMENT_PART)}
    sc = imp.scores(entries, K=K)
    out = {}
    for prof in sc["parent"]:
        p, c, h, x = (sc[k].get(prof) for k in ("parent", "child", "hyp_only", "exp_only"))
        if None in (p, c, h, x):
            continue
        hyp = ((h - p) + (c - x)) / 2
        exp = ((x - p) + (c - h)) / 2
        out[prof] = {"total": round(c - p, 3), "hypothesis": round(hyp, 3), "experiment": round(exp, 3)}
    return out

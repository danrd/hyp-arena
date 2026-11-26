"""Offline evaluator for normalize_card/v19 and verify_claim/v23 A/B batch packets.

Validates returned batch JSON replies without network calls, applies deterministic code
post-processors (`normalizer.v19_code_fields` and `verifier.enforce_relation_to_claim`),
and computes exact comparison metrics against:
  1. D01-D50 reference annotations & development-extraction-check.json (`mode="normalize"`),
  2. Blinded reader key combining dev-deep observations + sensitivity anchors (`mode="reader"`).

Usage:
    python scripts/calibration/score_ab_packets.py normalize --replies dir_or_file.json --dev60 working-dev60.json --cases working-dev60-cases.json --baseline-check development-extraction-check.json
    python scripts/calibration/score_ab_packets.py reader --replies dir_or_file.json --key reader_key.json
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Optional

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from hyparena.card import normalizer
from hyparena.card.models import Claim, EvidenceRecord, HypothesisCard
from hyparena.reading import verifier


def _toks(s: str) -> list[str]:
    return re.findall(r"\w+", (s or "").lower())


def contiguous_overlap_65(a: str, b: str) -> bool:
    """Exact same proxy metric as development-extraction-check.json:
    contiguous token overlap >= 65% of shorter snippet (min 3 tokens; <3 requires exact match).
    """
    ta, tb = _toks(a), _toks(b)
    if not ta or not tb:
        return False
    short, long_ = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    if len(short) < 3:
        return short == long_
    need = math.ceil(len(short) * 0.65)
    s_long = " " + " ".join(long_) + " "
    for start in range(0, len(short) - need + 1):
        sub = " " + " ".join(short[start : start + need]) + " "
        if sub in s_long:
            return True
    return False


def _load_reply_items(path: Path, list_key: str) -> list[dict[str, Any]]:
    files = sorted(path.glob("*.json")) if path.is_dir() else [path]
    out: list[dict[str, Any]] = []
    for f in files:
        raw = json.loads(f.read_text(encoding="utf-8"))
        if isinstance(raw, list):
            out.extend(x for x in raw if isinstance(x, dict))
        elif isinstance(raw, dict):
            if isinstance(raw.get(list_key), list):
                out.extend(x for x in raw[list_key] if isinstance(x, dict))
            elif "case_id" in raw or "item_id" in raw or "id" in raw:
                out.append(raw)
    return out


def score_normalize_replies(
    replies: list[dict[str, Any]],
    dev60_records: list[dict[str, Any]],
    cases_by_id: dict[str, dict[str, Any]],
    baseline_check: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    ref_by_id = {str(r["case_id"]): r for r in dev60_records}
    base_rows = {str(r["case_id"]): r for r in (baseline_check or {}).get("rows", [])}

    role_map = {
        "mechanism": "mechanism",
        "outcome": "outcome",
        "novel_claim": "novel_contribution",
    }
    totals = {k: {"ref_explicit": 0, "any_overlap": 0, "role_overlap": 0} for k in role_map}
    contrast_eligible = 0
    contrast_hits = 0
    diagnostic_cases: dict[str, Any] = {}
    valid_cards = 0
    verbatim_claim_spans = [0, 0]  # [matched, total]
    bg_leak_violations = 0

    for item in replies:
        cid = str(item.get("case_id") or item.get("id") or "")
        card_payload = item.get("card") if isinstance(item.get("card"), dict) else item
        if not cid or cid not in cases_by_id or cid not in ref_by_id:
            continue

        c_src = cases_by_id[cid]
        raw_text = "\n".join(x for x in (c_src.get("claim"), c_src.get("rationale"), c_src.get("experiment")) if x)
        cleaned = normalizer._closed_fields(card_payload)
        card = HypothesisCard.model_validate({**cleaned, "id": cid, "raw_id": cid})
        normalizer.v15_prepare(card)
        normalizer.design_from_registry(card, raw_text)
        normalizer.derive_roles(card)
        normalizer.v13_code_fields(card, raw_text)
        normalizer.v19_code_fields(card, raw_text)
        valid_cards += 1

        for cl in card.claims:
            if cl.source_span:
                verbatim_claim_spans[1] += 1
                if normalizer._norm_text(cl.source_span) in normalizer._norm_text(raw_text):
                    verbatim_claim_spans[0] += 1
            if "background" in (cl.chain_roles or []) and len(cl.chain_roles) == 1 and cl.required_for_balance:
                bg_leak_violations += 1

        ref = ref_by_id[cid]
        for ref_role, card_role in role_map.items():
            ref_links = [
                lnk
                for lnk in (ref.get("A", {}).get("links") or [])
                if lnk.get("status") == "explicit"
                and ref_role in (lnk.get("roles") or [])
                and ((lnk.get("card_quote") or {}).get("text") or "").strip()
            ]
            for rlnk in ref_links:
                qtxt = rlnk["card_quote"]["text"]
                totals[ref_role]["ref_explicit"] += 1
                any_hit = any(contiguous_overlap_65(qtxt, cl.source_span) for cl in card.claims if cl.source_span)
                role_hit = any(
                    contiguous_overlap_65(qtxt, cl.source_span)
                    for cl in card.claims
                    if cl.source_span and card_role in (cl.chain_roles or [])
                )
                if any_hit:
                    totals[ref_role]["any_overlap"] += 1
                if role_hit:
                    totals[ref_role]["role_overlap"] += 1

        # Contrast evaluation
        b_row = base_rows.get(cid)
        ref_contrast = ((ref.get("C", {}).get("adequacy", {}).get("control_or_outcome_quote") or {}).get("text") or "").strip()
        if b_row and b_row.get("contrast", {}).get("reference_eligible"):
            ref_c = b_row["contrast"]["reference"]
            contrast_eligible += 1
            cand_c = card.decisive_experiment.decisive_contrast_span or card.pico.comparator.span or ""
            hit = contiguous_overlap_65(cand_c, ref_c)
            if hit:
                contrast_hits += 1
            if cid in ("D13", "D23", "D41", "D47"):
                diagnostic_cases[cid] = {"overlap": hit, "extracted": cand_c}
        elif ref_contrast:
            cand_c = card.decisive_experiment.decisive_contrast_span or card.pico.comparator.span or ""
            if cid in ("D13", "D23", "D41", "D47"):
                diagnostic_cases[cid] = {"overlap": contiguous_overlap_65(cand_c, ref_contrast), "extracted": cand_c}

    return {
        "n_evaluated_cards": valid_cards,
        "verbatim_claim_spans": {"matched": verbatim_claim_spans[0], "total": verbatim_claim_spans[1]},
        "background_required_leak_violations": bg_leak_violations,
        "role_overlap": totals,
        "decisive_contrast": {
            "eligible": contrast_eligible,
            "v19_overlap": contrast_hits,
            "rate": round(contrast_hits / contrast_eligible, 4) if contrast_eligible else None,
            "diagnostic_cases": diagnostic_cases,
        },
    }


def score_reader_replies(
    replies: list[dict[str, Any]],
    key_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    by_id = {str(r.get("item_id") or r.get("id") or ""): r for r in replies}
    classes = ("direct_support", "direct_contradiction", "related", "irrelevant", "insufficient")

    raw_pairs: list[tuple[str, str, str, str]] = []   # (item_id, split_kind, expected, raw_pred)
    guarded_pairs: list[tuple[str, str, str, str]] = []

    for iid, meta in sorted(key_by_id.items()):
        if iid not in by_id:
            continue
        ans = by_id[iid]
        exp_rel = meta["expected_relation"]
        split_kind = meta["subset"]  # "dev_specificity" | "anchor_support" | "anchor_contradiction" | "anchor_trap"
        raw_rel = str(ans.get("relation_to_claim") or "insufficient").strip()

        # Construct EvidenceRecord + Claim to apply deterministic enforce_relation_to_claim
        rec = EvidenceRecord(
            source="PubMed",
            record_id=f"PMID:{meta['pmid']}",
            species=str(ans.get("species") or "unknown"),
            endpoint=ans.get("endpoint") if ans.get("endpoint") in ("lifespan", "healthspan", "biomarker", "disease", "mechanism", "unknown") else "unknown",
            qualifiers_match=ans.get("qualifiers_match") if isinstance(ans.get("qualifiers_match"), dict) else {},
            outcome_match=ans.get("outcome_match") if ans.get("outcome_match") in ("same", "narrower", "broader", "other", "") else "",
            actual_contrast=str(ans.get("actual_contrast") or ""),
            actual_system=str(ans.get("actual_system") or ""),
            actual_outcome=str(ans.get("actual_outcome") or ""),
            relation_to_claim=raw_rel if raw_rel in classes else "insufficient",
            study_mode=ans.get("study_mode") if ans.get("study_mode") in ("confirmatory", "exploratory", "unknown") else None,
            worst_domain_risk=ans.get("worst_domain_risk") if ans.get("worst_domain_risk") in ("low", "some_concerns", "high", "unknown", "not_applicable") else None,
        )
        dummy_claim = Claim(
            id="c1",
            subject=meta.get("claim_subject") or "intervention",
            relation="improves_healthspan_in",
            object=meta.get("claim_object") or "outcome",
            role=meta.get("claim_role") if meta.get("claim_role") in ("premise", "mechanism", "analog", "outcome", "translation") else "outcome",
        )
        guarded = verifier.enforce_relation_to_claim(rec, dummy_claim)
        guard_rel = guarded.relation_to_claim or "insufficient"

        raw_pairs.append((iid, split_kind, exp_rel, raw_rel))
        guarded_pairs.append((iid, split_kind, exp_rel, guard_rel))

    def _summarize(pairs: list[tuple[str, str, str, str]]) -> dict[str, Any]:
        n = len(pairs)
        acc = round(sum(1 for _, _, e, p in pairs if e == p) / n, 4) if n else None
        per_subset: dict[str, dict[str, Any]] = {}
        for sub in ("dev_specificity", "anchor_support", "anchor_contradiction", "anchor_trap"):
            sub_p = [(i, e, p) for i, s, e, p in pairs if s == sub]
            if sub_p:
                ok = sum(1 for _, e, p in sub_p if e == p)
                per_subset[sub] = {
                    "correct": ok,
                    "total": len(sub_p),
                    "rate": round(ok / len(sub_p), 4),
                    "errors": [{"item_id": i, "expected": e, "predicted": p} for i, e, p in sub_p if e != p],
                }
        conf = Counter(f"{e} -> {p}" for _, _, e, p in pairs)
        return {
            "n_evaluated": n,
            "overall_accuracy": acc,
            "by_subset": per_subset,
            "confusion": dict(conf),
        }

    return {
        "raw_model": _summarize(raw_pairs),
        "post_enforce_guard": _summarize(guarded_pairs),
    }


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="mode", required=True)

    p_norm = sub.add_parser("normalize", help="Score normalize_card/v19 replies on D01-D50.")
    p_norm.add_argument("--replies", type=Path, required=True, help="Reply JSON file or directory of JSON files.")
    p_norm.add_argument("--dev60", type=Path, required=True, help="Path to working-dev60.json.")
    p_norm.add_argument("--cases", type=Path, required=True, help="Path to working-dev60-cases.json.")
    p_norm.add_argument("--baseline-check", type=Path, default=None, help="Optional development-extraction-check.json.")

    p_read = sub.add_parser("reader", help="Score verify_claim/v23 replies against blinded reader_key.json.")
    p_read.add_argument("--replies", type=Path, required=True, help="Reply JSON file or directory of JSON files.")
    p_read.add_argument("--key", type=Path, required=True, help="Path to coordination/reader_key.json.")

    args = parser.parse_args(argv)
    if args.mode == "normalize":
        replies = _load_reply_items(args.replies, "cards")
        dev60 = json.loads(args.dev60.read_text(encoding="utf-8"))
        cdata = json.loads(args.cases.read_text(encoding="utf-8"))
        clist = cdata["cases"] if isinstance(cdata, dict) and "cases" in cdata else cdata
        cases_by_id = {str(c["case_id"]): c for c in clist}
        bchk = json.loads(args.baseline_check.read_text(encoding="utf-8")) if args.baseline_check else None
        res = score_normalize_replies(replies, dev60, cases_by_id, bchk)
    else:
        replies = _load_reply_items(args.replies, "items")
        kdata = json.loads(args.key.read_text(encoding="utf-8"))
        key_by_id = {str(k["item_id"]): k for k in (kdata["items"] if isinstance(kdata, dict) and "items" in kdata else kdata)}
        res = score_reader_replies(replies, key_by_id)

    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

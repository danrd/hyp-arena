"""Inter-annotator agreement calculator for Hyp-Arena calibration annotations.

Compares two annotation JSON files (single objects or lists of objects) matched by case_id.
Reports exact agreement, unweighted Cohen's kappa (when marginal variance > 0), confusion
counts, and case-level disagreements across Blocks A, B, and C.

Usage:
    python scripts/calibration/annotation_agreement.py annotator_a.json annotator_b.json
    python scripts/calibration/annotation_agreement.py a.json b.json --json
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any, Optional


def cohens_kappa(pairs: list[tuple[Any, Any]]) -> Optional[float]:
    """Compute unweighted Cohen's kappa for paired categorical labels.

    Returns None when pairs is empty or expected agreement pe >= 1.0 (zero marginal variance).
    """
    n = len(pairs)
    if n == 0:
        return None
    po = sum(1 for a, b in pairs if a == b) / n
    ca = Counter(a for a, _ in pairs)
    cb = Counter(b for _, b in pairs)
    labels = set(ca) | set(cb)
    pe = sum((ca[lbl] / n) * (cb[lbl] / n) for lbl in labels)
    if pe >= 1.0 - 1e-12:
        return None
    return round((po - pe) / (1.0 - pe), 4)


def _metric_summary(
    name: str,
    pairs: list[tuple[str, Any, Any]],
    skip_both_none: bool = True,
) -> dict[str, Any]:
    filtered = [(cid, a, b) for cid, a, b in pairs if not (skip_both_none and a is None and b is None)]
    n = len(filtered)
    agree = sum(1 for _, a, b in filtered if a == b)
    label_pairs = [(a, b) for _, a, b in filtered]
    kappa = cohens_kappa(label_pairs)
    disagreements = [
        {"id": cid, "annotator_a": a, "annotator_b": b}
        for cid, a, b in filtered
        if a != b
    ]
    confusion: dict[str, int] = {}
    for a, b in label_pairs:
        key = f"{a} -> {b}"
        confusion[key] = confusion.get(key, 0) + 1
    return {
        "field": name,
        "n": n,
        "n_agree": agree,
        "agreement_rate": round(agree / n, 4) if n else None,
        "cohens_kappa": kappa,
        "confusion": confusion,
        "disagreements": disagreements,
    }


def _load_by_case(path: Path) -> dict[str, dict[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    items = raw if isinstance(raw, list) else [raw]
    return {str(r["case_id"]): r for r in items}


def _has_explicit_novel(rec: dict[str, Any]) -> bool:
    for lnk in rec.get("A", {}).get("links") or []:
        if lnk.get("status") == "explicit" and "novel_claim" in (lnk.get("roles") or []):
            return True
    return False


def _obs_by_pmid(rec: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for obs in rec.get("B", {}).get("observations") or []:
        pmid = str(obs.get("pmid") or "").strip()
        if pmid:
            out.setdefault(pmid, []).append(obs)
    return out


def compute_agreement(
    map_a: dict[str, dict[str, Any]],
    map_b: dict[str, dict[str, Any]],
    case_ids: Optional[list[str]] = None,
) -> dict[str, Any]:
    shared = sorted(set(map_a) & set(map_b))
    if case_ids is not None:
        wanted = set(case_ids)
        shared = [cid for cid in shared if cid in wanted]

    only_a = sorted(set(map_a) - set(map_b))
    only_b = sorted(set(map_b) - set(map_a))

    # Track whether either annotator lacked literature access on each case.
    lit_access_mismatch: list[str] = []
    for cid in shared:
        sa = map_a[cid].get("B", {}).get("additional_search_status")
        sb = map_b[cid].get("B", {}).get("additional_search_status")
        if (sa == "unavailable") != (sb == "unavailable"):
            lit_access_mismatch.append(cid)

    # Case-level field extractors
    a_explicit_novel: list[tuple[str, Any, Any]] = []
    b_add_search: list[tuple[str, Any, Any]] = []
    c_alt_origin: list[tuple[str, Any, Any]] = []
    c_on_pos: list[tuple[str, Any, Any]] = []
    c_on_null: list[tuple[str, Any, Any]] = []
    c_best_class: list[tuple[str, Any, Any]] = []
    c_tested_scope: list[tuple[str, Any, Any]] = []
    c_has_precision: list[tuple[str, Any, Any]] = []
    c_feas_status: list[tuple[str, Any, Any]] = []
    c_feas_tier: list[tuple[str, Any, Any]] = []

    # Observation-level (case_id:pmid) pairs
    b_relation_all: list[tuple[str, Any, Any]] = []
    b_relation_comparable: list[tuple[str, Any, Any]] = []
    b_study_mode: list[tuple[str, Any, Any]] = []
    b_worst_risk: list[tuple[str, Any, Any]] = []

    for cid in shared:
        ra, rb = map_a[cid], map_b[cid]
        a_explicit_novel.append((cid, _has_explicit_novel(ra), _has_explicit_novel(rb)))
        b_add_search.append((cid, ra["B"].get("additional_search_status"), rb["B"].get("additional_search_status")))

        ca, cb = ra["C"], rb["C"]
        c_alt_origin.append((cid, ca["alternative"].get("origin"), cb["alternative"].get("origin")))
        c_on_pos.append((cid, ca["alternative"].get("on_positive"), cb["alternative"].get("on_positive")))
        c_on_null.append((cid, ca["alternative"].get("on_null"), cb["alternative"].get("on_null")))
        c_best_class.append((cid, ca["adequacy"].get("endpoint_best_class"), cb["adequacy"].get("endpoint_best_class")))
        c_tested_scope.append((cid, ca["adequacy"].get("tested_scope"), cb["adequacy"].get("tested_scope")))
        c_has_precision.append(
            (
                cid,
                bool(str(ca["adequacy"].get("precision_basis") or "").strip()),
                bool(str(cb["adequacy"].get("precision_basis") or "").strip()),
            )
        )
        c_feas_status.append((cid, ca["feasibility"].get("evidence_status"), cb["feasibility"].get("evidence_status")))
        c_feas_tier.append((cid, ca["feasibility"].get("resource_tier"), cb["feasibility"].get("resource_tier")))

        oa_map, ob_map = _obs_by_pmid(ra), _obs_by_pmid(rb)
        for pmid in sorted(set(oa_map) & set(ob_map)):
            # Pair primary observation for that PMID (first entry when unique; multi-entry compared by index)
            n_pair = min(len(oa_map[pmid]), len(ob_map[pmid]))
            for idx in range(n_pair):
                oa, ob = oa_map[pmid][idx], ob_map[pmid][idx]
                pid = f"{cid}:PMID{pmid}" if n_pair == 1 else f"{cid}:PMID{pmid}#{idx + 1}"
                rel_a, rel_b = oa.get("relation"), ob.get("relation")
                b_relation_all.append((pid, rel_a, rel_b))
                if cid not in lit_access_mismatch:
                    b_relation_comparable.append((pid, rel_a, rel_b))
                b_study_mode.append((pid, oa.get("study_mode"), ob.get("study_mode")))
                b_worst_risk.append((pid, oa.get("worst_domain_risk"), ob.get("worst_domain_risk")))

    metrics = [
        _metric_summary("A.has_explicit_novel_claim", a_explicit_novel, skip_both_none=False),
        _metric_summary("B.additional_search_status", b_add_search),
        _metric_summary("B.observation.relation (all paired PMIDs)", b_relation_all),
        _metric_summary("B.observation.relation (comparable lit access)", b_relation_comparable),
        _metric_summary("B.observation.study_mode", b_study_mode),
        _metric_summary("B.observation.worst_domain_risk", b_worst_risk),
        _metric_summary("C.alternative.origin", c_alt_origin),
        _metric_summary("C.alternative.on_positive", c_on_pos),
        _metric_summary("C.alternative.on_null", c_on_null),
        _metric_summary("C.adequacy.has_precision_basis", c_has_precision, skip_both_none=False),
        _metric_summary("C.adequacy.endpoint_best_class", c_best_class),
        _metric_summary("C.adequacy.tested_scope", c_tested_scope),
        _metric_summary("C.feasibility.evidence_status", c_feas_status),
        _metric_summary("C.feasibility.resource_tier", c_feas_tier),
    ]

    return {
        "shared_cases": shared,
        "only_in_a": only_a,
        "only_in_b": only_b,
        "lit_access_mismatch_cases": lit_access_mismatch,
        "metrics": metrics,
    }


def format_markdown(result: dict[str, Any]) -> str:
    lines = [
        "# Inter-Annotator Agreement Report",
        "",
        f"- Shared cases ({len(result['shared_cases'])}): {', '.join(result['shared_cases']) or 'none'}",
    ]
    if result["only_in_a"]:
        lines.append(f"- Only in A: {', '.join(result['only_in_a'])}")
    if result["only_in_b"]:
        lines.append(f"- Only in B: {', '.join(result['only_in_b'])}")
    if result["lit_access_mismatch_cases"]:
        lines.append(
            "- Literature-access mismatch (`unavailable` in one annotator only): "
            + ", ".join(result["lit_access_mismatch_cases"])
        )
    lines.extend(
        [
            "",
            "| Field | N | Agree | Rate | Cohen's kappa |",
            "| --- | ---: | ---: | ---: | ---: |",
        ]
    )
    for m in result["metrics"]:
        if m["n"] == 0:
            continue
        rate = f"{m['agreement_rate']:.2%}" if m["agreement_rate"] is not None else "n/a"
        kappa = f"{m['cohens_kappa']:.3f}" if m["cohens_kappa"] is not None else "n/a (0 var)"
        lines.append(f"| `{m['field']}` | {m['n']} | {m['n_agree']} | {rate} | {kappa} |")

    dis_blocks = [m for m in result["metrics"] if m["disagreements"]]
    if dis_blocks:
        lines.extend(["", "## Disagreements", ""])
        for m in dis_blocks:
            lines.append(f"### `{m['field']}`")
            for d in m["disagreements"]:
                lines.append(f"- `{d['id']}`: A=`{d['annotator_a']}` vs B=`{d['annotator_b']}`")
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Compute inter-annotator agreement for Hyp-Arena annotations.")
    parser.add_argument("annotator_a", type=Path, help="First annotator JSON file.")
    parser.add_argument("annotator_b", type=Path, help="Second annotator JSON file.")
    parser.add_argument("--cases", nargs="*", default=None, help="Optional subset of case_ids to compare.")
    parser.add_argument("--json", action="store_true", help="Output JSON instead of Markdown.")
    args = parser.parse_args(argv)

    res = compute_agreement(_load_by_case(args.annotator_a), _load_by_case(args.annotator_b), case_ids=args.cases)
    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        print(format_markdown(res))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

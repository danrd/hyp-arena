"""Validator for Hyp-Arena calibration annotation JSON files (v1 / v1.1 compatible).

Checks:
1. Structural & enum conformance against specs/evaluation/annotation_v1.schema.json (no extra deps required).
2. Verbatim substring verification for every card quote against cases.json (when --cases is provided).
3. Optional verbatim verification for literature quotes against a saved abstracts JSON map (--abstracts).
4. Conditional methodological rules from docs/plans/evaluation-annotation-tasks-2026-11-25.md
   (errors vs non-blocking diagnostic warnings).

Usage:
    python scripts/calibration/validate_annotation.py path/to/responses.json --cases path/to/cases.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

SCHEMA_PATH = Path(__file__).resolve().parents[2] / "specs" / "evaluation" / "annotation_v1.schema.json"

LINK_ROLES = {"mechanism", "outcome", "novel_claim"}
LINK_STATUSES = {"explicit", "implicit", "insufficient", None}
OBS_ORIGINS = {"fixed_candidates", "additional_search", None}
OBS_RELATIONS = {"direct_support", "direct_contradiction", "related", "irrelevant", "insufficient", None}
STUDY_MODES = {"confirmatory", "exploratory", "unknown", None}
WORST_DOMAIN_RISKS = {"low", "some_concerns", "high", "unknown", "not_applicable", None}
ADD_SEARCH_STATUSES = {"done", "unavailable", "not_needed", None}
ALT_ORIGINS = {"stated_by_author", "annotator", "not_applicable", None}
ALT_FATES = {"eliminated", "weakened", "unchanged", None}
BEST_CLASSES = {"target_engagement", "exploratory_biomarker", "validated_surrogate", "direct_clinical", "unknown", None}
PRECISION_STATUSES = {"stated_for_contrast", "general_principle_only", "missing", None}
TESTED_SCOPES = {"direct", "prerequisite", "unclear", None}
EXT_VALIDITY_FLAGS = {
    "single_sex",
    "young_healthy_for_ageing",
    "nam_systemic_extrapolation",
    "unvalidated_surrogate",
    "prognostic_vs_predictive_conflation",
    "other",
}
EVIDENCE_STATUSES = {"confirmed_in_context", "adjacent_only", "insufficient", "not_applicable", None}
RESOURCE_TIERS = {"1_in_vitro", "2_animal", "3_human_ex_vivo_or_pilot", "4_clinical_in_vivo", None}
SAFETY_FLAGS = {
    "on_target_pleiotropy",
    "irreversible_no_ltfu",
    "unjustified_risk_in_healthy_older",
    "missing_diseased_organ_model",
    "other",
}
GENETIC_STATUSES = {
    "strong_human_genetics",
    "suggestive_human_genetics",
    "conflicting_human_genetics",
    "no_human_genetics",
    "not_applicable",
    "unknown",
    None,
}
PLEIOTROPY_RISKS = {"none", "low", "moderate", "high", "unknown", "not_applicable", None}
CARD_FIELDS = ("claim", "rationale", "experiment")

ELLIPSIS_RE = re.compile(r"\.\.\.|…")
LINK_ID_RE = re.compile(r"^L[0-9]+$")
PMID_IN_LOC_RE = re.compile(r"\bPMID[:\s]*(\d{6,9})\b", re.IGNORECASE)
NEGATIVE_PRECISION_RE = re.compile(
    r"(?:не\s+указан\w*|не\s+привед\w*|отсутству\w*|нет\s+(?:расч|планов|обоснован|числа)|расч[её]т\s+мощности\s+не|"
    r"указано\s+только\s+общее\s+число|указан\s+только\s+(?:общий\s+)?принцип|"
    r"not\s+(?:stated|reported|specified|provided)|no\s+(?:power|sample[- ]size|precision)|only\s+general\s+principle)",
    re.IGNORECASE,
)


@dataclass
class Issue:
    case_id: str
    path: str
    severity: str  # "error" or "warning"
    code: str
    message: str

    def as_dict(self) -> dict[str, str]:
        return {
            "case_id": self.case_id,
            "path": self.path,
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
        }


@dataclass
class ValidationReport:
    n_records: int = 0
    card_quotes_checked: int = 0
    card_quotes_matched: int = 0
    lit_quotes_checked: int = 0
    lit_quotes_matched: int = 0
    issues: list[Issue] = field(default_factory=list)

    @property
    def errors(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == "error"]

    @property
    def warnings(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == "warning"]

    def as_dict(self) -> dict[str, Any]:
        return {
            "n_records": self.n_records,
            "n_errors": len(self.errors),
            "n_warnings": len(self.warnings),
            "card_quotes_checked": self.card_quotes_checked,
            "card_quotes_matched": self.card_quotes_matched,
            "lit_quotes_checked": self.lit_quotes_checked,
            "lit_quotes_matched": self.lit_quotes_matched,
            "issues": [i.as_dict() for i in self.issues],
        }


def _norm_ws(s: str) -> str:
    """Normalize whitespace and unicode compatibility spaces (e.g. thin space) without altering words."""
    s = unicodedata.normalize("NFKC", s)
    return re.sub(r"\s+", " ", s).strip()


def _nonempty_str(v: Any) -> bool:
    return isinstance(v, str) and bool(v.strip())


def _is_nullable_str(v: Any) -> bool:
    return v is None or isinstance(v, str)


def _check_keys(
    obj: dict[str, Any],
    required: set[str],
    optional: set[str],
    case_id: str,
    path: str,
    issues: list[Issue],
) -> None:
    keys = set(obj.keys())
    for missing in sorted(required - keys):
        issues.append(Issue(case_id, f"{path}.{missing}", "error", "missing_key", f"Missing required key '{missing}'"))
    for extra in sorted(keys - (required | optional)):
        issues.append(Issue(case_id, f"{path}.{extra}", "error", "unknown_key", f"Unexpected key '{extra}'"))


def _check_quote_shape(q: Any, case_id: str, path: str, issues: list[Issue]) -> Optional[dict[str, Any]]:
    if not isinstance(q, dict):
        issues.append(Issue(case_id, path, "error", "invalid_type", "Quote must be an object with 'text' and 'location'"))
        return None
    _check_keys(q, {"text", "location"}, set(), case_id, path, issues)
    if not _is_nullable_str(q.get("text")):
        issues.append(Issue(case_id, f"{path}.text", "error", "invalid_type", "Quote text must be string or null"))
    if not _is_nullable_str(q.get("location")):
        issues.append(Issue(case_id, f"{path}.location", "error", "invalid_type", "Quote location must be string or null"))
    if _nonempty_str(q.get("text")) and not _nonempty_str(q.get("location")):
        issues.append(Issue(case_id, f"{path}.location", "error", "missing_location", "Non-empty quote requires a location"))
    return q


def _resolve_card_field(location: str, case_id: str = "") -> Optional[str]:
    loc = location.strip().lower()
    if case_id:
        cid = case_id.strip().lower()
        for sep in (".", ":", "/", " "):
            if loc.startswith(cid + sep):
                loc = loc[len(cid) + len(sep) :].strip()
                break
    # Also strip generic case-id prefix like d04.claim or c01.experiment
    loc = re.sub(r"^[a-z]{1,4}\d{1,3}\s*[.:/]\s*", "", loc)
    if loc in CARD_FIELDS:
        return loc
    for f in CARD_FIELDS:
        if loc.startswith(f + " ") or loc.startswith(f + "(") or loc.startswith(f + ":") or loc.startswith(f + ","):
            return f
    return None


def _extract_pmid_from_location(location: Optional[str]) -> Optional[str]:
    if not location:
        return None
    m = PMID_IN_LOC_RE.search(location)
    return m.group(1) if m else None


def _verify_card_quote(
    q: Optional[dict[str, Any]],
    case_obj: Optional[dict[str, Any]],
    case_id: str,
    path: str,
    report: ValidationReport,
) -> None:
    if not q or not _nonempty_str(q.get("text")):
        return
    text = q["text"]
    loc = q.get("location") or ""
    field_name = _resolve_card_field(loc, case_id)
    if field_name is None:
        # Location points to an external paper (e.g. PMID ...) rather than a card field.
        return
    if case_obj is None:
        return

    report.card_quotes_checked += 1
    source = case_obj.get(field_name)
    if not isinstance(source, str) or not source:
        report.issues.append(
            Issue(case_id, path, "error", "empty_source_field", f"Card field '{field_name}' is empty in cases.json")
        )
        return

    if text in source or _norm_ws(text) in _norm_ws(source):
        report.card_quotes_matched += 1
        return

    if ELLIPSIS_RE.search(text) and not ELLIPSIS_RE.search(source):
        report.issues.append(
            Issue(
                case_id,
                f"{path}.text",
                "error",
                "spliced_quote_ellipsis",
                f"Quote contains ellipsis and is not a contiguous verbatim substring of card.{field_name}",
            )
        )
    else:
        report.issues.append(
            Issue(
                case_id,
                f"{path}.text",
                "error",
                "quote_not_found",
                f"Quote not found verbatim in card.{field_name}",
            )
        )


def _verify_lit_quote(
    q: Optional[dict[str, Any]],
    pmid: Optional[str],
    abstracts: Optional[dict[str, dict[str, Any]]],
    case_id: str,
    path: str,
    report: ValidationReport,
) -> None:
    if not q or not _nonempty_str(q.get("text")) or not abstracts or not pmid:
        return
    rec = abstracts.get(str(pmid).strip())
    if not rec:
        return
    haystack = " ".join(str(rec.get(k) or "") for k in ("title", "abstract"))
    if not haystack.strip():
        return
    report.lit_quotes_checked += 1
    text = q["text"]
    if text in haystack or _norm_ws(text) in _norm_ws(haystack):
        report.lit_quotes_matched += 1
    else:
        severity = "warning" if ELLIPSIS_RE.search(text) else "warning"
        report.issues.append(
            Issue(
                case_id,
                f"{path}.text",
                severity,
                "lit_quote_not_in_abstract",
                f"Quote not matched verbatim in saved title/abstract for PMID {pmid} (may be from full text or spliced)",
            )
        )


def validate_record(
    rec: Any,
    cases_by_id: Optional[dict[str, dict[str, Any]]] = None,
    abstracts: Optional[dict[str, dict[str, Any]]] = None,
    report: Optional[ValidationReport] = None,
) -> ValidationReport:
    if report is None:
        report = ValidationReport()
    issues = report.issues
    report.n_records += 1

    if not isinstance(rec, dict):
        issues.append(Issue("<unknown>", "$", "error", "invalid_type", "Annotation record must be a JSON object"))
        return report

    case_id = str(rec.get("case_id") or "<missing>")
    _check_keys(rec, {"case_id", "A", "B", "C"}, {"schema_version"}, case_id, "$", issues)
    if not _nonempty_str(rec.get("case_id")):
        issues.append(Issue(case_id, "$.case_id", "error", "missing_case_id", "case_id must be a non-empty string"))
    sv = rec.get("schema_version")
    if sv is not None and sv not in {"1.0", "1.1"}:
        issues.append(Issue(case_id, "$.schema_version", "error", "invalid_enum", f"Invalid schema_version: {sv!r}"))

    case_obj = cases_by_id.get(case_id) if cases_by_id else None
    if cases_by_id is not None and case_obj is None:
        issues.append(Issue(case_id, "$.case_id", "error", "unknown_case_id", f"case_id '{case_id}' not found in cases.json"))

    # --- Block A ---
    link_ids: set[str] = set()
    block_a = rec.get("A")
    if not isinstance(block_a, dict):
        issues.append(Issue(case_id, "$.A", "error", "invalid_type", "Block A must be an object"))
    else:
        _check_keys(block_a, {"links", "measured_outcome", "unresolved_transition"}, set(), case_id, "$.A", issues)
        links = block_a.get("links")
        if not isinstance(links, list) or len(links) == 0:
            issues.append(Issue(case_id, "$.A.links", "error", "empty_links", "A.links must be a non-empty array"))
        else:
            for idx, lnk in enumerate(links):
                lp = f"$.A.links[{idx}]"
                if not isinstance(lnk, dict):
                    issues.append(Issue(case_id, lp, "error", "invalid_type", "Link entry must be an object"))
                    continue
                _check_keys(
                    lnk,
                    {"id", "roles", "statement", "system_or_population", "direction", "conditions", "status", "card_quote", "notes"},
                    {"human_genetic_anchor"},
                    case_id,
                    lp,
                    issues,
                )
                lid = lnk.get("id")
                if not isinstance(lid, str) or not LINK_ID_RE.match(lid):
                    issues.append(Issue(case_id, f"{lp}.id", "error", "invalid_link_id", f"Invalid link id {lid!r}; expected L1, L2, ..."))
                elif lid in link_ids:
                    issues.append(Issue(case_id, f"{lp}.id", "error", "duplicate_link_id", f"Duplicate link id '{lid}'"))
                else:
                    link_ids.add(lid)

                roles = lnk.get("roles")
                if not isinstance(roles, list) or not roles:
                    issues.append(Issue(case_id, f"{lp}.roles", "error", "invalid_roles", "Link roles must be a non-empty array"))
                else:
                    if len(roles) != len(set(roles)):
                        issues.append(Issue(case_id, f"{lp}.roles", "error", "duplicate_roles", "Link roles contain duplicates"))
                    for r in roles:
                        if r not in LINK_ROLES:
                            issues.append(Issue(case_id, f"{lp}.roles", "error", "invalid_enum", f"Invalid role {r!r}"))

                st = lnk.get("status")
                if st not in LINK_STATUSES:
                    issues.append(Issue(case_id, f"{lp}.status", "error", "invalid_enum", f"Invalid link status {st!r}"))

                cq = _check_quote_shape(lnk.get("card_quote"), case_id, f"{lp}.card_quote", issues)
                _verify_card_quote(cq, case_obj, case_id, f"{lp}.card_quote", report)

                if st == "explicit" and (not cq or not _nonempty_str(cq.get("text"))):
                    issues.append(Issue(case_id, f"{lp}.card_quote", "error", "missing_quote", "Explicit link requires a verbatim card_quote"))
                if st == "implicit" and cq and _nonempty_str(cq.get("text")):
                    issues.append(Issue(case_id, f"{lp}.card_quote", "warning", "implicit_has_quote", "Implicit link normally has null card_quote"))
                if st in ("implicit", "insufficient") and not _nonempty_str(lnk.get("notes")):
                    issues.append(Issue(case_id, f"{lp}.notes", "warning", "missing_explanation", f"Link with status '{st}' should explain why in notes"))

                hga = lnk.get("human_genetic_anchor")
                if hga is not None:
                    if not isinstance(hga, dict):
                        issues.append(Issue(case_id, f"{lp}.human_genetic_anchor", "error", "invalid_type", "human_genetic_anchor must be object or null"))
                    else:
                        _check_keys(hga, set(), {"status", "pleiotropy_risk", "source", "notes"}, case_id, f"{lp}.human_genetic_anchor", issues)
                        if hga.get("status") not in GENETIC_STATUSES:
                            issues.append(Issue(case_id, f"{lp}.human_genetic_anchor.status", "error", "invalid_enum", f"Invalid genetic status {hga.get('status')!r}"))
                        if hga.get("pleiotropy_risk") not in PLEIOTROPY_RISKS:
                            issues.append(Issue(case_id, f"{lp}.human_genetic_anchor.pleiotropy_risk", "error", "invalid_enum", f"Invalid pleiotropy_risk {hga.get('pleiotropy_risk')!r}"))

    # --- Block B ---
    block_b = rec.get("B")
    if not isinstance(block_b, dict):
        issues.append(Issue(case_id, "$.B", "error", "invalid_type", "Block B must be an object"))
    else:
        _check_keys(
            block_b,
            {"observations", "additional_search_status", "queries", "already_tested_and_remaining", "limits"},
            set(),
            case_id,
            "$.B",
            issues,
        )
        add_st = block_b.get("additional_search_status")
        if add_st not in ADD_SEARCH_STATUSES:
            issues.append(Issue(case_id, "$.B.additional_search_status", "error", "invalid_enum", f"Invalid additional_search_status {add_st!r}"))
        if add_st == "unavailable" and not _nonempty_str(block_b.get("limits")):
            issues.append(Issue(case_id, "$.B.limits", "error", "missing_limits", "additional_search_status='unavailable' requires an explanation in B.limits"))
        if not isinstance(block_b.get("queries"), list):
            issues.append(Issue(case_id, "$.B.queries", "error", "invalid_type", "B.queries must be an array"))

        obs_list = block_b.get("observations")
        if not isinstance(obs_list, list):
            issues.append(Issue(case_id, "$.B.observations", "error", "invalid_type", "B.observations must be an array"))
        else:
            seen_pmids: set[str] = set()
            for idx, obs in enumerate(obs_list):
                op = f"$.B.observations[{idx}]"
                if not isinstance(obs, dict):
                    issues.append(Issue(case_id, op, "error", "invalid_type", "Observation must be an object"))
                    continue
                _check_keys(
                    obs,
                    {
                        "pmid",
                        "origin",
                        "link_id",
                        "contrast",
                        "system_or_population",
                        "outcome",
                        "direction",
                        "relation",
                        "why",
                        "comparison_quote",
                        "result_quote",
                        "risk_notes",
                    },
                    {"study_mode", "worst_domain_risk"},
                    case_id,
                    op,
                    issues,
                )
                if _nonempty_str(obs.get("pmid")):
                    seen_pmids.add(str(obs["pmid"]).strip())
                if obs.get("origin") not in OBS_ORIGINS:
                    issues.append(Issue(case_id, f"{op}.origin", "error", "invalid_enum", f"Invalid observation origin {obs.get('origin')!r}"))
                rel = obs.get("relation")
                if rel not in OBS_RELATIONS:
                    issues.append(Issue(case_id, f"{op}.relation", "error", "invalid_enum", f"Invalid relation {rel!r}"))
                if obs.get("study_mode") not in STUDY_MODES:
                    issues.append(Issue(case_id, f"{op}.study_mode", "error", "invalid_enum", f"Invalid study_mode {obs.get('study_mode')!r}"))
                if obs.get("worst_domain_risk") not in WORST_DOMAIN_RISKS:
                    issues.append(Issue(case_id, f"{op}.worst_domain_risk", "error", "invalid_enum", f"Invalid worst_domain_risk {obs.get('worst_domain_risk')!r}"))

                olid = obs.get("link_id")
                if olid is not None and link_ids and olid not in link_ids:
                    issues.append(Issue(case_id, f"{op}.link_id", "error", "dangling_link_id", f"Observation link_id '{olid}' not in A.links {sorted(link_ids)}"))

                comp_q = _check_quote_shape(obs.get("comparison_quote"), case_id, f"{op}.comparison_quote", issues)
                res_q = _check_quote_shape(obs.get("result_quote"), case_id, f"{op}.result_quote", issues)
                _verify_lit_quote(comp_q, obs.get("pmid"), abstracts, case_id, f"{op}.comparison_quote", report)
                _verify_lit_quote(res_q, obs.get("pmid"), abstracts, case_id, f"{op}.result_quote", report)

                if not isinstance(obs.get("risk_notes"), list):
                    issues.append(Issue(case_id, f"{op}.risk_notes", "error", "invalid_type", "risk_notes must be an array"))

                if rel == "related" and not _nonempty_str(obs.get("why")):
                    issues.append(Issue(case_id, f"{op}.why", "error", "missing_why", "relation='related' requires explaining the difference in why"))
                if rel in ("direct_support", "direct_contradiction"):
                    for req_f in ("contrast", "system_or_population", "outcome", "direction"):
                        if not _nonempty_str(obs.get(req_f)):
                            issues.append(Issue(case_id, f"{op}.{req_f}", "error", "missing_direct_field", f"relation='{rel}' requires non-empty '{req_f}'"))
                    if not res_q or not _nonempty_str(res_q.get("text")):
                        issues.append(Issue(case_id, f"{op}.result_quote", "error", "missing_result_quote", f"relation='{rel}' requires result_quote.text"))

            if case_obj and isinstance(case_obj.get("candidate_pmids"), list):
                for cpmid in case_obj["candidate_pmids"]:
                    if str(cpmid).strip() not in seen_pmids:
                        issues.append(
                            Issue(
                                case_id,
                                "$.B.observations",
                                "warning",
                                "missing_candidate_pmid",
                                f"Candidate PMID {cpmid} from cases.json has no observation entry in B",
                            )
                        )

    # --- Block C ---
    block_c = rec.get("C")
    if not isinstance(block_c, dict):
        issues.append(Issue(case_id, "$.C", "error", "invalid_type", "Block C must be an object"))
    else:
        _check_keys(block_c, {"alternative", "adequacy", "feasibility"}, set(), case_id, "$.C", issues)

        # C.alternative
        alt = block_c.get("alternative")
        adeq = block_c.get("adequacy")
        feas = block_c.get("feasibility")

        precision_str = adeq.get("precision_basis") if isinstance(adeq, dict) else None
        precision_status = adeq.get("precision_status") if isinstance(adeq, dict) else None
        precision_is_neg_prose = bool(_nonempty_str(precision_str) and NEGATIVE_PRECISION_RE.search(precision_str))
        if precision_status is not None:
            precision_present = precision_status == "stated_for_contrast"
        else:
            precision_present = bool(_nonempty_str(precision_str) and not precision_is_neg_prose)
        engagement_present = isinstance(adeq, dict) and _nonempty_str(adeq.get("engagement_check"))

        if not isinstance(alt, dict):
            issues.append(Issue(case_id, "$.C.alternative", "error", "invalid_type", "C.alternative must be an object"))
        else:
            _check_keys(
                alt,
                {
                    "explanation",
                    "origin",
                    "basis",
                    "basis_quote",
                    "control_quote",
                    "prediction_hypothesis",
                    "prediction_alternative",
                    "remaining_loophole",
                    "on_positive",
                    "on_null",
                    "why",
                },
                {"contrast_id", "null_outcomes"},
                case_id,
                "$.C.alternative",
                issues,
            )
            if alt.get("origin") not in ALT_ORIGINS:
                issues.append(Issue(case_id, "$.C.alternative.origin", "error", "invalid_enum", f"Invalid alternative origin {alt.get('origin')!r}"))
            on_pos = alt.get("on_positive")
            on_null = alt.get("on_null")
            if on_pos not in ALT_FATES:
                issues.append(Issue(case_id, "$.C.alternative.on_positive", "error", "invalid_enum", f"Invalid on_positive {on_pos!r}"))
            if on_null not in ALT_FATES:
                issues.append(Issue(case_id, "$.C.alternative.on_null", "error", "invalid_enum", f"Invalid on_null {on_null!r}"))

            bq = _check_quote_shape(alt.get("basis_quote"), case_id, "$.C.alternative.basis_quote", issues)
            cq = _check_quote_shape(alt.get("control_quote"), case_id, "$.C.alternative.control_quote", issues)
            _verify_card_quote(bq, case_obj, case_id, "$.C.alternative.basis_quote", report)
            _verify_card_quote(cq, case_obj, case_id, "$.C.alternative.control_quote", report)

            has_ctrl = bool(cq and _nonempty_str(cq.get("text")))
            if on_pos in ("weakened", "eliminated") and not has_ctrl:
                issues.append(
                    Issue(
                        case_id,
                        "$.C.alternative.control_quote",
                        "error",
                        "ungrounded_discrimination",
                        f"on_positive='{on_pos}' requires a verbatim control_quote from the protocol",
                    )
                )
            if on_pos == "eliminated":
                ph = alt.get("prediction_hypothesis")
                pa = alt.get("prediction_alternative")
                if not _nonempty_str(ph) or not _nonempty_str(pa):
                    issues.append(
                        Issue(
                            case_id,
                            "$.C.alternative",
                            "error",
                            "missing_predictions",
                            "on_positive='eliminated' requires both prediction_hypothesis and prediction_alternative",
                        )
                    )
                elif _norm_ws(ph).casefold() == _norm_ws(pa).casefold():
                    issues.append(
                        Issue(
                            case_id,
                            "$.C.alternative",
                            "error",
                            "identical_predictions",
                            "on_positive='eliminated' requires distinct hypothesis and alternative predictions",
                        )
                    )
                if _nonempty_str(alt.get("remaining_loophole")):
                    issues.append(
                        Issue(
                            case_id,
                            "$.C.alternative.remaining_loophole",
                            "warning",
                            "eliminated_with_loophole",
                            "on_positive='eliminated' while remaining_loophole is non-empty; verify whether loophole explains the claimed outcome",
                        )
                    )
            if on_null in ("weakened", "eliminated"):
                if not precision_present:
                    issues.append(
                        Issue(
                            case_id,
                            "$.C.alternative.on_null",
                            "warning",
                            "null_credit_without_precision",
                            f"on_null='{on_null}' while C.adequacy.precision_basis is null (conditional judgment pending precision)",
                        )
                    )
                if not engagement_present:
                    issues.append(
                        Issue(
                            case_id,
                            "$.C.alternative.on_null",
                            "warning",
                            "null_credit_without_engagement",
                            f"on_null='{on_null}' while C.adequacy.engagement_check is null",
                        )
                    )

            null_outcomes = alt.get("null_outcomes")
            if null_outcomes is not None:
                if not isinstance(null_outcomes, list):
                    issues.append(Issue(case_id, "$.C.alternative.null_outcomes", "error", "invalid_type", "null_outcomes must be an array"))
                else:
                    for idx, no in enumerate(null_outcomes):
                        np = f"$.C.alternative.null_outcomes[{idx}]"
                        if not isinstance(no, dict):
                            issues.append(Issue(case_id, np, "error", "invalid_type", "null_outcome entry must be an object"))
                            continue
                        _check_keys(
                            no,
                            {"contrast_id", "null_definition", "on_null", "why"},
                            {"prediction_alternative", "precision_basis"},
                            case_id,
                            np,
                            issues,
                        )
                        if no.get("on_null") not in ALT_FATES:
                            issues.append(Issue(case_id, f"{np}.on_null", "error", "invalid_enum", f"Invalid on_null {no.get('on_null')!r}"))

        # C.adequacy
        if not isinstance(adeq, dict):
            issues.append(Issue(case_id, "$.C.adequacy", "error", "invalid_type", "C.adequacy must be an object"))
        else:
            _check_keys(
                adeq,
                {
                    "decisive_contrast",
                    "control_or_outcome_quote",
                    "measured_outcome",
                    "independent_unit",
                    "n_units_per_contrast",
                    "precision_basis",
                    "engagement_check",
                    "engagement_quote",
                    "positive_interpretation",
                    "null_interpretation",
                    "missing",
                },
                {"endpoint_best_class", "precision_status", "tested_scope", "external_validity_flags"},
                case_id,
                "$.C.adequacy",
                issues,
            )
            coq = _check_quote_shape(adeq.get("control_or_outcome_quote"), case_id, "$.C.adequacy.control_or_outcome_quote", issues)
            eq = _check_quote_shape(adeq.get("engagement_quote"), case_id, "$.C.adequacy.engagement_quote", issues)
            _verify_card_quote(coq, case_obj, case_id, "$.C.adequacy.control_or_outcome_quote", report)
            _verify_card_quote(eq, case_obj, case_id, "$.C.adequacy.engagement_quote", report)

            if adeq.get("precision_status") not in PRECISION_STATUSES:
                issues.append(Issue(case_id, "$.C.adequacy.precision_status", "error", "invalid_enum", f"Invalid precision_status {adeq.get('precision_status')!r}"))
            if precision_is_neg_prose and adeq.get("precision_status") != "general_principle_only":
                issues.append(
                    Issue(
                        case_id,
                        "$.C.adequacy.precision_basis",
                        "warning",
                        "negative_text_in_precision_basis",
                        "precision_basis describes missing power/precision or general principle only; use null + C.adequacy.missing or set precision_status",
                    )
                )

            if adeq.get("endpoint_best_class") not in BEST_CLASSES:
                issues.append(Issue(case_id, "$.C.adequacy.endpoint_best_class", "error", "invalid_enum", f"Invalid endpoint_best_class {adeq.get('endpoint_best_class')!r}"))
            if adeq.get("tested_scope") not in TESTED_SCOPES:
                issues.append(Issue(case_id, "$.C.adequacy.tested_scope", "error", "invalid_enum", f"Invalid tested_scope {adeq.get('tested_scope')!r}"))
            evf = adeq.get("external_validity_flags")
            if evf is not None:
                if not isinstance(evf, list):
                    issues.append(Issue(case_id, "$.C.adequacy.external_validity_flags", "error", "invalid_type", "external_validity_flags must be an array"))
                else:
                    for fl in evf:
                        if fl not in EXT_VALIDITY_FLAGS:
                            issues.append(Issue(case_id, "$.C.adequacy.external_validity_flags", "error", "invalid_enum", f"Invalid external_validity_flag {fl!r}"))

        # C.feasibility
        if not isinstance(feas, dict):
            issues.append(Issue(case_id, "$.C.feasibility", "error", "invalid_type", "C.feasibility must be an object"))
        else:
            _check_keys(
                feas,
                {
                    "tool_or_class",
                    "target_system",
                    "evidence_status",
                    "evidence_quote",
                    "key_resource_or_dependency",
                    "tradeoff",
                    "notes",
                },
                {"resource_tier", "component_checks", "safety_flags"},
                case_id,
                "$.C.feasibility",
                issues,
            )
            ev_st = feas.get("evidence_status")
            if ev_st not in EVIDENCE_STATUSES:
                issues.append(Issue(case_id, "$.C.feasibility.evidence_status", "error", "invalid_enum", f"Invalid evidence_status {ev_st!r}"))
            evq = _check_quote_shape(feas.get("evidence_quote"), case_id, "$.C.feasibility.evidence_quote", issues)
            _verify_card_quote(evq, case_obj, case_id, "$.C.feasibility.evidence_quote", report)
            _verify_lit_quote(
                evq,
                _extract_pmid_from_location((evq or {}).get("location")),
                abstracts,
                case_id,
                "$.C.feasibility.evidence_quote",
                report,
            )
            if ev_st in ("confirmed_in_context", "adjacent_only") and (not evq or not _nonempty_str(evq.get("text"))):
                issues.append(
                    Issue(
                        case_id,
                        "$.C.feasibility.evidence_quote",
                        "error",
                        "missing_readiness_quote",
                        f"evidence_status='{ev_st}' requires a supporting evidence_quote",
                    )
                )
            if feas.get("resource_tier") not in RESOURCE_TIERS:
                issues.append(Issue(case_id, "$.C.feasibility.resource_tier", "error", "invalid_enum", f"Invalid resource_tier {feas.get('resource_tier')!r}"))
            sflags = feas.get("safety_flags")
            if sflags is not None:
                if not isinstance(sflags, list):
                    issues.append(Issue(case_id, "$.C.feasibility.safety_flags", "error", "invalid_type", "safety_flags must be an array"))
                else:
                    for fl in sflags:
                        if fl not in SAFETY_FLAGS:
                            issues.append(Issue(case_id, "$.C.feasibility.safety_flags", "error", "invalid_enum", f"Invalid safety_flag {fl!r}"))
            cchecks = feas.get("component_checks")
            if cchecks is not None:
                if not isinstance(cchecks, list):
                    issues.append(Issue(case_id, "$.C.feasibility.component_checks", "error", "invalid_type", "component_checks must be an array"))
                else:
                    for idx, cc in enumerate(cchecks):
                        cp = f"$.C.feasibility.component_checks[{idx}]"
                        if not isinstance(cc, dict):
                            issues.append(Issue(case_id, cp, "error", "invalid_type", "component_check must be an object"))
                            continue
                        _check_keys(cc, {"component", "target_system", "evidence_status"}, {"evidence_quote", "notes"}, case_id, cp, issues)
                        if cc.get("evidence_status") not in (EVIDENCE_STATUSES - {None}):
                            issues.append(Issue(case_id, f"{cp}.evidence_status", "error", "invalid_enum", f"Invalid component evidence_status {cc.get('evidence_status')!r}"))
                        if "evidence_quote" in cc and cc["evidence_quote"] is not None:
                            ccq = _check_quote_shape(cc["evidence_quote"], case_id, f"{cp}.evidence_quote", issues)
                            _verify_card_quote(ccq, case_obj, case_id, f"{cp}.evidence_quote", report)
                            _verify_lit_quote(
                                ccq,
                                _extract_pmid_from_location((ccq or {}).get("location")),
                                abstracts,
                                case_id,
                                f"{cp}.evidence_quote",
                                report,
                            )

    return report


def validate_file(
    path: Path,
    cases_path: Optional[Path] = None,
    abstracts_path: Optional[Path] = None,
) -> ValidationReport:
    raw = json.loads(path.read_text(encoding="utf-8"))
    records = raw if isinstance(raw, list) else [raw]

    cases_by_id: Optional[dict[str, dict[str, Any]]] = None
    if cases_path is not None:
        cdata = json.loads(cases_path.read_text(encoding="utf-8"))
        clist = cdata["cases"] if isinstance(cdata, dict) and "cases" in cdata else cdata
        cases_by_id = {str(c["case_id"]): c for c in clist}

    abstracts: Optional[dict[str, dict[str, Any]]] = None
    if abstracts_path is not None:
        abstracts = json.loads(abstracts_path.read_text(encoding="utf-8"))

    report = ValidationReport()
    for rec in records:
        validate_record(rec, cases_by_id=cases_by_id, abstracts=abstracts, report=report)
    return report


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Validate Hyp-Arena calibration annotation JSON files.")
    parser.add_argument("annotations", type=Path, help="Path to annotation JSON (single object or list of objects).")
    parser.add_argument("--cases", type=Path, default=None, help="Optional path to packet cases.json for verbatim card quote checks.")
    parser.add_argument("--abstracts", type=Path, default=None, help="Optional JSON map of PMID -> {title, abstract}.")
    parser.add_argument("--json", action="store_true", help="Output report as JSON.")
    parser.add_argument("--strict-warnings", action="store_true", help="Return non-zero exit code if warnings are present.")
    args = parser.parse_args(argv)

    report = validate_file(args.annotations, cases_path=args.cases, abstracts_path=args.abstracts)
    if args.json:
        print(json.dumps(report.as_dict(), ensure_ascii=False, indent=2))
    else:
        print(
            f"Validated {report.n_records} record(s): "
            f"{len(report.errors)} error(s), {len(report.warnings)} warning(s) | "
            f"card quotes: {report.card_quotes_matched}/{report.card_quotes_checked}"
        )
        if report.lit_quotes_checked:
            print(f"Literature quotes matched in abstracts: {report.lit_quotes_matched}/{report.lit_quotes_checked}")
        for iss in report.issues:
            print(f"  [{iss.severity.upper()}] {iss.case_id} {iss.path} ({iss.code}): {iss.message}")

    if report.errors or (args.strict_warnings and report.warnings):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

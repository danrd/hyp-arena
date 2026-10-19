"""Expert layer (card spec 7a; Aggregation_Spec 6a): expert decisions kept apart from the declared and verified
layers. What each decision does:
- with a `source` on a claim (or a rejected alternative): the source goes through the verifier like any other
  record, so it can change the claim's status only through the usual rules;
- without a source: stays in this layer and is shown as "expert opinion", never as a fact;
- `pairwise` ("prefer H-A" on targets [H-A, H-B]): a weight constraint Prefer(H-A >= H-B) in the named profile
  (or every profile); rankings are reported with and without these constraints;
- `portfolio` and `pairwise` are also validation labels; hypotheses the expert writes go through the same
  pipeline with origin "expert".

The file is YAML:

    decisions:
      - {id: e1, by: "...", at: 2026-10-20, point: evidence_conflict, hypothesis: H-0003, target: a1,
         decision: accept, rationale: "...", source: "PMID:23863708"}
      - {id: e2, by: "...", at: 2026-10-20, point: pairwise, target: [H-0001, H-0002], decision: prefer H-0001,
         profile: evidence_first}
    hypotheses:
      - "Text of a hypothesis written by the expert."
"""
from __future__ import annotations

import re
from dataclasses import replace
from pathlib import Path
from typing import Optional, Union

import yaml

from hyparena.aspid import Prefer, Profile
from hyparena.card.models import ExpertDecision, ExpertLayer


def load(path: Union[str, Path, None]) -> ExpertLayer:
    if not path:
        return ExpertLayer()
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    for d in data.get("decisions") or []:
        if d.get("at") is not None:
            d["at"] = str(d["at"])                    # YAML reads bare dates as dates
    return ExpertLayer.model_validate(data)


def _pmid(source: str) -> Optional[str]:
    m = re.fullmatch(r"\s*(?:PMID:?\s*)?(\d{4,9})\s*", source or "", flags=re.I)
    return m.group(1) if m else None


def sources(layer: ExpertLayer, hypothesis: str) -> dict[str, list[tuple[str, str]]]:
    """Claim id → [(PMID, decision id)] for decisions with a PubMed source on this hypothesis's claims."""
    out: dict[str, list[tuple[str, str]]] = {}
    for d in layer.decisions:
        pmid = _pmid(d.source or "")
        if d.hypothesis == hypothesis and isinstance(d.target, str) and pmid:
            out.setdefault(d.target, []).append((pmid, d.id))
    return out


def opinions(layer: ExpertLayer, hypothesis: str) -> list[dict]:
    """Decisions on this hypothesis (or naming it as a target), each marked as an expert opinion or as a source
    that went through the verifier."""
    out = []
    for d in layer.decisions:
        targets = d.target if isinstance(d.target, list) else [d.target]
        if d.hypothesis == hypothesis or hypothesis in targets:
            out.append({**d.model_dump(), "kind": "source sent to the verifier" if _pmid(d.source or "")
                        and d.hypothesis == hypothesis else "expert opinion"})
    return out


def preferences(layer: ExpertLayer) -> dict[Optional[str], list[Prefer]]:
    """Pairwise decisions as Prefer constraints, by profile name (None: every profile)."""
    out: dict[Optional[str], list[Prefer]] = {}
    for d in layer.decisions:
        if d.point != "pairwise":
            continue
        if not isinstance(d.target, list) or len(d.target) != 2:
            raise ValueError(f"{d.id}: a pairwise decision targets two hypotheses")
        m = re.fullmatch(r"\s*prefer\s+(\S+)\s*", d.decision, flags=re.I)
        if not m or m.group(1) not in d.target:
            raise ValueError(f"{d.id}: decision must be 'prefer <one of {d.target}>'")
        a = m.group(1)
        b = next(t for t in d.target if t != a)
        out.setdefault(d.profile, []).append(Prefer(a, b, ">=", by=d.by or d.id, at=d.at))
    return out


def with_preferences(profiles: dict[str, Profile], prefs: dict[Optional[str], list[Prefer]]) -> dict[str, Profile]:
    """Copies of the profiles with the expert constraints added; the version records how many were added."""
    unknown = [p for p in prefs if p is not None and p not in profiles]
    if unknown:
        raise ValueError(f"pairwise decisions name unknown profiles: {unknown}")
    out = {}
    for name, p in profiles.items():
        extra = prefs.get(None, []) + prefs.get(name, [])
        out[name] = replace(p, prefer=list(p.prefer) + extra,
                            version=f"{p.version}+expert-{len(extra)}" if extra else p.version)
    return out

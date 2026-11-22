"""ClinicalTrials.gov API v2 connector: registered human studies (status, phase, dates, enrollment).

Evidence tier 1 (registry record). `as_of` keeps studies first submitted on or before the date
(`AREA[StudyFirstSubmitDate]RANGE[MIN,date]`); the status and completion shown are as of today, so in
backtests they can still reveal later developments (flagged in the record's extra)."""
from __future__ import annotations

import json
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from hyparena.coscientist.state import Evidence
from hyparena.tools.http import Http

URL = "https://clinicaltrials.gov/api/v2/studies"
PHASE_CACHE = Path(__file__).resolve().parents[2] / "data" / "cache" / "ct_readiness.json"
PHASE_MAP = {"EARLY_PHASE1": 1, "PHASE1": 1, "PHASE2": 2, "PHASE3": 3, "PHASE4": 4}
_phase_cache: Optional[dict] = None
_phase_lock = threading.Lock()


def _norm_key(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", (text or "").casefold()))


def _candidate_names(label: str) -> list[str]:
    """Full label without parentheticals plus short parenthetical code/alias (e.g. 'bimokalner (ACOU085)')."""
    if not label:
        return []
    out: list[str] = []
    parens = re.findall(r"\(([^()]{2,40})\)", label)
    stripped = re.sub(r"\([^()]*\)", " ", label)
    stripped = re.sub(r"\s+", " ", stripped).strip(" ,;:-")
    if stripped:
        out.append(stripped)
    for part in parens:
        part = part.strip()
        if part and not re.match(r"^(e\.g\.|i\.e\.|mg|µM|mM|nM|Hz|kHz)", part, re.I):
            out.append(part)
    seen, res = set(), []
    for item in out:
        key = _norm_key(item)
        if key and key not in seen:
            seen.add(key)
            res.append(item)
    return res


def _load_phase_cache() -> dict:
    global _phase_cache
    if _phase_cache is None:
        _phase_cache = json.loads(PHASE_CACHE.read_text(encoding="utf-8")) if PHASE_CACHE.exists() else {}
    return _phase_cache


def _save_phase_cache(cache: dict) -> None:
    PHASE_CACHE.parent.mkdir(parents=True, exist_ok=True)
    PHASE_CACHE.write_text(json.dumps(cache, indent=2, ensure_ascii=False), encoding="utf-8")


def compound_phase(label: str, as_of: str = "", *, http: Optional[Http] = None) -> dict:
    """Strict ClinicalTrials.gov v2 fallback for a compound up to as_of (StudyFirstSubmitDate <= as_of).
    Returns {'matched': bool, 'max_phase': Optional[int], 'ncts': list[str]}."""
    candidates = _candidate_names(label)
    if not candidates:
        return {"matched": False, "max_phase": None, "ncts": []}
    client = http or Http()
    best_phase: Optional[int] = None
    matched_ncts: list[str] = []
    matched_any = False
    for cand in candidates:
        cand_k = _norm_key(cand)
        cache_key = f"{cand_k}|{as_of}"
        with _phase_lock:
            cache = _load_phase_cache()
            studies = cache.get(cache_key)
        if studies is None:
            params = {"query.intr": cand, "pageSize": "15"}
            if as_of:
                params["filter.advanced"] = f"AREA[StudyFirstSubmitDate]RANGE[MIN,{as_of}]"
            data = client.get_json(URL, params)
            if not isinstance(data, dict):
                continue
            studies = []
            for st in data.get("studies", []):
                ps = st.get("protocolSection", {})
                nct = ps.get("identificationModule", {}).get("nctId", "")
                phases = ps.get("designModule", {}).get("phases", []) or []
                intrs = []
                for intr in ps.get("armsInterventionsModule", {}).get("interventions", []) or []:
                    intrs.append({"name": intr.get("name", ""), "otherNames": intr.get("otherNames", []) or []})
                studies.append({"nct": nct, "phases": phases, "interventions": intrs})
            with _phase_lock:
                cache = _load_phase_cache()
                cache[cache_key] = studies
                _save_phase_cache(cache)
        cand_tokens = set(cand_k.split())
        for st in studies:
            hit = False
            for intr in st.get("interventions", []):
                for nm in [intr.get("name", ""), *(intr.get("otherNames") or [])]:
                    nk = _norm_key(nm)
                    if not nk:
                        continue
                    if nk == cand_k or (len(cand_tokens) == 1 and len(cand_k) >= 4 and cand_k in nk.split()):
                        hit = True
                        break
                    if len(cand_tokens) >= 2 and cand_k in nk:
                        hit = True
                        break
                if hit:
                    break
            if hit:
                matched_any = True
                if st.get("nct") and st["nct"] not in matched_ncts:
                    matched_ncts.append(st["nct"])
                for ph in st.get("phases", []):
                    pv = PHASE_MAP.get(ph)
                    if pv is not None and (best_phase is None or pv > best_phase):
                        best_phase = pv
    return {"matched": matched_any, "max_phase": best_phase, "ncts": matched_ncts[:5]}


class ClinicalTrialsSearch:
    def __init__(self, http: Optional[Http] = None):
        self.http = http or Http()
        self._cache: dict[tuple, list[Evidence]] = {}
        self._lock = threading.Lock()

    def search(self, query: str, limit: int = 5, as_of: Optional[str] = None) -> list[Evidence]:
        key = (query, limit, as_of)
        with self._lock:
            if key in self._cache:
                return self._cache[key]
        params = {"query.term": query, "pageSize": str(limit)}
        if as_of:
            params["filter.advanced"] = f"AREA[StudyFirstSubmitDate]RANGE[MIN,{as_of}]"
        data = self.http.get_json(URL, params) or {}
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        out = []
        for st in data.get("studies", []):
            p = st.get("protocolSection", {})
            ident, status, design = p.get("identificationModule", {}), p.get("statusModule", {}), p.get("designModule", {})
            desc = p.get("descriptionModule", {})
            enroll = design.get("enrollmentInfo", {})
            phases = ", ".join(design.get("phases", []) or []) or "n/a"
            comp = status.get("completionDateStruct", {})
            text = (f"Status: {status.get('overallStatus')}; phase: {phases}; "
                    f"start: {status.get('startDateStruct', {}).get('date')}; "
                    f"completion: {comp.get('date')} ({comp.get('type', 'unknown')}); "
                    f"enrollment: {enroll.get('count')} ({enroll.get('type', 'unknown')}). "
                    f"{(desc.get('briefSummary') or '')[:500]}")
            out.append(Evidence(
                source="clinicaltrials", record_id=f"NCT:{ident.get('nctId')}", title=ident.get("briefTitle", ""),
                text=text, url=f"https://clinicaltrials.gov/study/{ident.get('nctId')}",
                publication_date=status.get("studyFirstSubmitDate"), retrieved_at=now, query=query, tier=1,
                study_type=f"registered study ({design.get('studyType', 'unknown')})", species="human",
                epistemic_type="plans",
                extra={"status_as_of_retrieval": True} if as_of else {}))
        with self._lock:
            self._cache[key] = out
        return out

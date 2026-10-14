"""ClinicalTrials.gov API v2 connector: registered human studies (status, phase, dates, enrollment).

Evidence tier 1 (registry record). `as_of` keeps studies first submitted on or before the date
(`AREA[StudyFirstSubmitDate]RANGE[MIN,date]`); the status and completion shown are as of today, so in
backtests they can still reveal later developments (flagged in the record's extra)."""
from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Optional

from hyparena.state import Evidence
from hyparena.tools.http import Http

URL = "https://clinicaltrials.gov/api/v2/studies"


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
                extra={"status_as_of_retrieval": True} if as_of else {}))
        with self._lock:
            self._cache[key] = out
        return out

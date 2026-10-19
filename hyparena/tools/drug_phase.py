"""Maximum clinical phase of a compound (ChEMBL data via the Open Targets Platform GraphQL API; the ChEMBL REST
API returned errors when this was written). Used for the translational-distance indicator. Cached."""
from __future__ import annotations

from functools import lru_cache
from typing import Optional

import httpx

URL = "https://api.platform.opentargets.org/api/v4/graphql"
QUERY = ('query($q:String!){ search(queryString:$q, entityNames:["drug"], page:{index:0,size:1})'
         '{ hits{ id name object{ ... on Drug { name maximumClinicalStage } } } } }')
STAGE = {"APPROVAL": 4, "PHASE_4": 4, "PHASE_3": 3, "PHASE_2_3": 2, "PHASE_2": 2, "PHASE_1_2": 1, "PHASE_1": 1,
         "EARLY_PHASE_1": 1, "PHASE_0": 0, "PRECLINICAL": 0}


@lru_cache(maxsize=512)
def lookup(name: str) -> Optional[tuple[str, str, int]]:
    """(ChEMBL id, preferred name, max phase 0..4) of the best match, or None if nothing is found."""
    try:
        r = httpx.post(URL, json={"query": QUERY, "variables": {"q": name}}, timeout=30)
        r.raise_for_status()
        hits = r.json()["data"]["search"]["hits"]
    except (httpx.HTTPError, KeyError, TypeError, ValueError):
        return None
    if not hits:
        return None
    h = hits[0]
    stage = (h.get("object") or {}).get("maximumClinicalStage") or ""
    return h["id"], h["name"], STAGE.get(stage, 0)


def max_phase(name: str) -> Optional[int]:
    hit = lookup(name)
    return hit[2] if hit else None

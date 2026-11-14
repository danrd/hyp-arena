"""DrugAge (HAGR, CC BY 3.0; de Magalhães et al. 2024): all rows of the current release, with the last good download kept."""
from __future__ import annotations

import csv
import io
import zipfile
from pathlib import Path

import httpx

DRUGAGE_URL = "https://genomics.senescence.info/drugs/dataset.zip"
DRUGAGE_CACHE = Path("data/cache/drugage.zip")      # the last good download (the site sometimes answers with a bot-check page)


def rows() -> list[dict]:
    """All rows of the current DrugAge release (downloaded each time; about 0.5 MB). When the download is not a zip archive
    (2026-11-02: the site answered with a reload page), the last good download in data/cache is used."""
    raw = b""
    try:
        raw = httpx.get(DRUGAGE_URL, timeout=120, follow_redirects=True).content
    except httpx.HTTPError:
        pass
    if raw[:2] == b"PK":
        DRUGAGE_CACHE.parent.mkdir(parents=True, exist_ok=True)
        DRUGAGE_CACHE.write_bytes(raw)
    elif DRUGAGE_CACHE.exists():
        raw = DRUGAGE_CACHE.read_bytes()
    else:
        raise RuntimeError("DrugAge: the download is not a zip archive and there is no cached copy (data/cache/drugage.zip)")
    z = zipfile.ZipFile(io.BytesIO(raw))
    return list(csv.DictReader(io.TextIOWrapper(z.open("drugage.csv"), encoding="utf-8", errors="replace")))

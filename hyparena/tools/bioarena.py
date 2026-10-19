"""Export of Bio Arena (bioarena.ru), an open tournament of hypotheses on ageing:
hypotheses with their texts, moderation and evidence dossiers, the Bradley–Terry ranking snapshot, and every
pairwise match with the judge's reasons. Read-only public JSON API of the site's own front end.

    python -m hyparena.tools.bioarena --out data/bioarena/2026-10-19

Writes status.json, ranking.json (all pages of one snapshot), hypotheses.jsonl.gz (one detail object per
hypothesis), matches.jsonl.gz (one match per line) and hypotheses.csv (flat summary). Polite: one request at
a time with a pause (three at a time for the slow detail pages); details are cached under <out>/raw so an interrupted export resumes."""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

BASE = "https://bioarena.ru/api"
PAUSE = 0.35
RANKING_PAGE = 200      # the API accepts up to 200
MATCH_PAGE = 100        # the API accepts up to 100


def _get(session: httpx.Client, path: str, params: dict | None = None, tries: int = 5) -> dict:
    for attempt in range(tries):
        try:
            r = session.get(f"{BASE}{path}", params=params)
            if r.status_code == 200:
                time.sleep(PAUSE)
                return r.json()
            if r.status_code not in (429, 500, 502, 503, 504):
                raise RuntimeError(f"{path}: HTTP {r.status_code} {r.text[:200]}")
        except httpx.HTTPError:
            pass
        time.sleep(2 ** (attempt + 1))
    raise RuntimeError(f"{path}: failed after {tries} attempts")


def export(out: Path, log=print, workers: int = 3) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    raw = out / "raw"
    raw.mkdir(exist_ok=True)
    s = httpx.Client(timeout=60, headers={"User-Agent": "hyp-arena research export"})

    (out / "status.json").write_text(json.dumps(_get(s, "/status"), ensure_ascii=False, indent=1))

    # ranking: every page of one snapshot (the snapshot id pins the pages to the same calculation)
    first = _get(s, "/ranking", {"limit": RANKING_PAGE, "offset": 0})
    snapshot = first["snapshot"]["id"]
    rows, offset = list(first["hypotheses"]), RANKING_PAGE
    while offset < first["totalHypotheses"]:
        page = _get(s, "/ranking", {"limit": RANKING_PAGE, "offset": offset, "snapshot": snapshot})
        rows += page["hypotheses"]
        offset += RANKING_PAGE
    ranking = {**{k: v for k, v in first.items() if k != "hypotheses"}, "hypotheses": rows}
    (out / "ranking.json").write_text(json.dumps(ranking, ensure_ascii=False, indent=1))
    log(f"ranking: {len(rows)} of {first['totalHypotheses']} hypotheses, snapshot {snapshot[:12]}")

    # hypothesis details (cached one file each); the server takes 7-10 s per detail, so a few in parallel
    ids = list(dict.fromkeys(h["id"] for h in rows))
    todo = [hid for hid in ids if not (raw / f"h_{hid}.json").exists()]

    def one(hid):
        (raw / f"h_{hid}.json").write_text(json.dumps(_get(s, f"/hypotheses/{hid}"), ensure_ascii=False))

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for i, _ in enumerate(pool.map(one, todo), 1):
            if i % 50 == 0:
                log(f"details: {len(ids) - len(todo) + i}/{len(ids)}")
    with gzip.open(out / "hypotheses.jsonl.gz", "wt", encoding="utf-8") as g:
        for hid in ids:
            g.write((raw / f"h_{hid}.json").read_text() + "\n")

    # matches, newest first as the API serves them; pages cached
    first_m = _get(s, "/matches", {"limit": MATCH_PAGE, "offset": 0})
    total = first_m["total"]
    for offset in range(0, total, MATCH_PAGE):
        f = raw / f"m_{offset:05d}.json"
        if not f.exists():
            page = first_m if offset == 0 else _get(s, "/matches", {"limit": MATCH_PAGE, "offset": offset})
            f.write_text(json.dumps(page, ensure_ascii=False))
    seen, matches = set(), []
    for offset in range(0, total, MATCH_PAGE):
        for m in json.loads((raw / f"m_{offset:05d}.json").read_text())["matches"]:
            if m["id"] not in seen:        # pages can shift while the tournament runs
                seen.add(m["id"])
                matches.append(m)
    with gzip.open(out / "matches.jsonl.gz", "wt", encoding="utf-8") as g:
        for m in matches:
            g.write(json.dumps(m, ensure_ascii=False) + "\n")
    log(f"matches: {len(matches)} unique of {total}")

    _summary(out, rows)
    judge_call(out, s, ids)
    return {"hypotheses": len(ids), "matches": len(matches), "snapshot": snapshot}


def judge_call(out: Path, s: httpx.Client, ids: list[str]) -> None:
    """One full call of the match judge (instructions, input dossiers, verdict): the judge prompt is not in the
    match records."""
    for hid in ids:
        d = json.loads((out / "raw" / f"h_{hid}.json").read_text())
        call = next((c for c in d.get("recentCalls") or [] if c.get("stage") == "matches" and c.get("status") == "succeeded"), None)
        if call:
            data = _get(s, f"/hypotheses/{hid}/calls/{call['id']}")
            (out / "judge_call_example.json").write_text(json.dumps(data, ensure_ascii=False, indent=1))
            (out / "judge_instructions.txt").write_text(data["request"]["instructions"])
            return


def _summary(out: Path, rows: list[dict]) -> None:
    """Flat table: ranking fields plus status, moderation and the text length from the details."""
    rank = {h["id"]: h for h in rows}
    with gzip.open(out / "hypotheses.jsonl.gz", "rt", encoding="utf-8") as g, \
            open(out / "hypotheses.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id", "title", "author", "status", "moderation", "state", "rank", "rating", "rating_lower",
                    "rating_upper", "wins", "losses", "planned", "completed", "created_at", "dossier", "text_chars"])
        for line in g:
            d = json.loads(line)
            h = d.get("hypothesis", {})
            r = rank.get(h.get("id"), {})
            unc = r.get("uncertainty") or {}
            w.writerow([h.get("id"), h.get("title"), h.get("author"), h.get("status"),
                        (d.get("moderation") or {}).get("category"), r.get("state"), r.get("rank"),
                        r.get("rating"), unc.get("lower"), unc.get("upper"), r.get("wins"), r.get("losses"),
                        r.get("planned"), r.get("completed"), h.get("createdAt"),
                        "yes" if (d.get("evidence") or {}).get("verified") else "no", len(h.get("description") or "")])


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    print(export(Path(args.out)))


if __name__ == "__main__":
    main()

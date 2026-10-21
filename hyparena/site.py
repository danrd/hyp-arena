"""Data bundle for the site (docs/site/index.html): one JSON with the hypotheses of a v2 run, their cards and
verification, the ranking under each preference profile, and, when given, the Elo ranking of a tournament run on
the same texts. The page shows a built-in example and loads any bundle written by this command.

    python -m hyparena.site export --v2 runs/neg_v2/v2-evidence_first-stage3/g003.v2.json \\
        --elo runs/neg/L0_s0/g003.json --pool data/negatives/drugage/g003.json --out runs/site/g003.json
    python -m hyparena.site embed --bundle runs/site/g003.json      # make it the page's built-in example

`--pool` names the input file of both runs: its ids join the tournament's results to the v2 items (the i-th
text of the pool is the i-th item of the v2 run). Without it the v2 item ids are used and `--elo` is ignored."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "docs" / "site" / "index.html"
QUOTE_MAX = 500
RECORDS_MAX = 12                     # per claim and side; the count of the rest is kept


def _title(text: str) -> str:
    first = next((ln.strip() for ln in text.splitlines() if ln.strip()), text.strip())
    first = re.sub(r"^(?:Hypothesis|Title)\s*:\s*", "", first)
    return first if len(first) <= 140 else first[:137] + "..."


def _record(r: dict) -> dict:
    out = {k: r.get(k) for k in ("source", "record_id", "linked_pmid", "species", "strain", "sex", "dose", "endpoint",
                                 "effect", "effect_percent", "study_type", "quote_role", "human_rungs", "flags")}
    out["quote"] = (r.get("quote") or "")[:QUOTE_MAX]
    out["intervention_match"] = (r.get("qualifiers_match") or {}).get("intervention_match", "")
    out["mismatch"] = [k for k, v in (r.get("qualifiers_match") or {}).items() if v == "no" and k != "intervention_match"]
    return {k: v for k, v in out.items() if v not in (None, "", [], "unknown")}


def _records(rs: list) -> dict:
    return {"items": [_record(r) for r in rs[:RECORDS_MAX]], "more": max(0, len(rs) - RECORDS_MAX)}


def _claim(c: dict) -> dict:
    return {"id": c["id"], "role": c.get("role"), "relation": c.get("relation"), "subject": c["subject"]["label"],
            "object": c["object"]["label"], "qualifiers": {k: v for k, v in (c.get("qualifiers") or {}).items()
                                                            if v and v != "unknown"},
            "inherited": c.get("inherited_from_pico") or [], "span": c.get("source_span", ""), "note": c.get("note", "")}


def _item(x: dict, pid: str) -> dict:
    card, ver = x.get("card") or {}, x.get("verification") or {}
    claims = {c["id"]: c for c in card.get("claims", []) + card.get("declared_alternatives", [])}
    verified = []
    for cv in ver.get("claims", []):
        c = cv.get("claim") or claims.get(cv["id"])
        verified.append({"id": cv["id"], "claim": _claim(c) if c else None, "status": cv.get("status"),
                         "rung_status": cv.get("rung_status") or {}, "flags": cv.get("flags") or [],
                         "contrast": cv.get("contrast") or {}, "notes": cv.get("notes", ""),
                         "evidence": _records(cv.get("evidence", [])), "counter": _records(cv.get("counterevidence", [])),
                         "refusals": [{k: r.get(k) for k in ("type", "record_id", "notes")} for r in cv.get("refusals", [])]})
    p = card.get("pico") or {}
    return {"id": pid, "card_id": x["id"], "title": _title(x["text"]), "text": x["text"], "outcome": x["outcome"],
            "duplicate_of": x.get("duplicate_of"), "repeats": x.get("repeats", 0),
            "admission": x.get("admission"), "problems": x.get("problems") or [],
            "card": {"claim_plain": card.get("claim_plain", ""), "type": card.get("hypothesis_type", ""),
                     "population": p.get("population"), "intervention": p.get("intervention"),
                     "comparator": p.get("comparator"), "outcome": p.get("outcome"),
                     "claims": [_claim(c) for c in card.get("claims", [])],
                     "alternatives_declared": [_claim(c) for c in card.get("declared_alternatives", [])],
                     "decisive_experiment": card.get("decisive_experiment")} if card else None,
            "verification": {"claims": verified, "profile": ver.get("evidence_profile"),
                             "known_result": ver.get("known_result"),
                             "alternatives": [{k: a.get(k) for k in ("id", "type", "source", "status", "explanation",
                                                                     "discriminating_design", "record_id", "quote")}
                                              for a in ver.get("alternatives", [])],
                             "searched": len(ver.get("searched_pmids") or [])} if ver else None,
            "indicators": x.get("indicators")}


def export(v2_path: str, elo_path: Optional[str] = None, pool_path: Optional[str] = None,
           title: str = "") -> dict:
    res = json.loads(Path(v2_path).read_text())
    ids = [x["id"] for x in res["items"]]
    if pool_path:
        from hyparena.data import load_imported
        ids = [h.id for h in load_imported(pool_path)][:len(res["items"])]
    to_pid = {x["id"]: pid for x, pid in zip(res["items"], ids)}
    items = [_item(x, pid) for x, pid in zip(res["items"], ids)]
    for it in items:
        if it["duplicate_of"]:
            it["duplicate_of"] = to_pid.get(it["duplicate_of"], it["duplicate_of"])
    profiles = {}
    for name, r in (res.get("ranking") or {}).items():
        profiles[name] = {"order": [to_pid[h] for h in r["order"]],
                          "expected": {to_pid[h]: v for h, v in r["expected"].items()},
                          "quantiles": {to_pid[h]: v for h, v in r["quantiles"].items()},
                          "p_topk": {to_pid[h]: v for h, v in r["p_topk"].items()},
                          "p_best": {to_pid[h]: v for h, v in r["p_best"].items()},
                          "pairwise": {to_pid[a]: {to_pid[b]: p for b, p in row.items()} for a, row in r["pairwise"].items()},
                          "k": r.get("meta", {}).get("k_top") or res["meta"].get("k_top"),
                          "mc_halfwidth": r.get("meta", {}).get("mc_halfwidth_max")}
    elo = None
    if elo_path and pool_path:
        t = json.loads(Path(elo_path).read_text())
        elo = {"rating": t["config"].get("rating"), "config": t["config"], "matches": t.get("matches"),
               "as_of": t.get("as_of"), "families": t.get("families"),
               "ratings": {h: {"rating": v.get("combined"), "status": v.get("status"),
                               "games": ((v.get("scores") or {}).get("overall") or {}).get("games")}
                           for h, v in t["hypotheses"].items() if h in set(ids)}}
    meta = res["meta"]
    return {"format": "hyparena-site@1", "title": title or Path(v2_path).stem,
            "meta": {"created": meta.get("created"), "as_of": meta.get("as_of"), "calls": meta.get("calls"),
                     "verifiers": meta.get("verifiers"), "profiles": meta.get("profiles"),
                     "indicators": meta.get("indicators"), "k_top": meta.get("k_top")},
            "hypotheses": items, "profiles": profiles, "elo": elo,
            "lists": {"filtered": {to_pid.get(h, h): r for h, r in (res.get("filtered") or {}).items()},
                      "known_results": [to_pid.get(h, h) for h in res.get("known_results") or []],
                      "outcome_counts": res.get("outcome_counts")}}


def embed(bundle_path: str, page: Path = PAGE) -> None:
    """Replace the page's built-in example with a bundle."""
    s = page.read_text(encoding="utf-8")
    data = json.dumps(json.loads(Path(bundle_path).read_text()), ensure_ascii=False, separators=(",", ":"))
    data = data.replace("</", "<\\/")
    new, n = re.subn(r'(<script id="sample" type="application/json">).*?(</script>)',
                     lambda m: m.group(1) + data + m.group(2), s, count=1, flags=re.S)
    if n != 1:
        raise ValueError("the page has no <script id=\"sample\" type=\"application/json\"> block")
    page.write_text(new, encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("export")
    e.add_argument("--v2", required=True, help="full v2 output (hyparena.card.pipeline)")
    e.add_argument("--elo", default=None, help="tournament result on the same texts (ladder format)")
    e.add_argument("--pool", default=None, help="the input file of both runs")
    e.add_argument("--title", default="")
    e.add_argument("--out", required=True)
    m = sub.add_parser("embed")
    m.add_argument("--bundle", required=True)
    a = ap.parse_args()
    if a.cmd == "export":
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(json.dumps(export(a.v2, a.elo, a.pool, a.title), ensure_ascii=False, indent=1))
        print(a.out)
    else:
        embed(a.bundle)


if __name__ == "__main__":
    main()

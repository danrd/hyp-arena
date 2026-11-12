"""The hypothesis database (specs/hypothesis-db-2026-11-09.yaml): one row per hypothesis or version, from every source we
hold, with a stable id, the short id, the text, the date it was written, the cut-off of its scoring, the outcome when known,
and where it is used (pools, Argon packs, data files). Free, deterministic, no model call. Rows and texts are private.

    python -m scripts.hypothesis_db build     # writes longevity-kg/hypothesis_db/rows.jsonl, short_ids.jsonl, README stats

Short ids: kept as given (never renumbered); a new one is given when a row first enters a scored or reported set
(benchmark v2, the outside reader's test pool), in source order; versions take the parent's id with the mode letter
(д tune, с free, н directed) and a number from the second version of the same mode. Rows of the wider pools (the 371
ongoing trials, Bio Arena, the ChatGPT set) have no short id until they are scored.
"""
from __future__ import annotations

import collections
import glob
import gzip
import json
import re
import sys
from pathlib import Path

import yaml

HA = Path(__file__).resolve().parents[1]
KG = HA.parent / "longevity-kg"
HS = KG / "hypothesis_sources"
DB = KG / "hypothesis_db"
MODE_LETTER = {"tune": "д", "free": "с", "directed": "н"}
REG_ID = re.compile(r"\b(NCT\d{8}|ISRCTN\d{8}|ACTRN\d{14}|DRKS\d{8}|NTR\d{3,5}|NL\d{4,6}|UMIN\d{9}|ChiCTR[\w-]+|CTRI/[\d/]+|jRCT\w+)\b")


def _prefix(source: str) -> str:
    return {"ctgov": "ctgov", "ctgov_2023": "ctgov", "trial_registry": "ctgov"}.get(source, source)


def _texts(path: Path) -> dict:
    return {json.loads(l)["id"]: json.loads(l) for l in path.read_text().splitlines() if l.strip()}


def rows() -> list[dict]:
    out: list[dict] = []

    def add(**r):
        r.setdefault("short", None)
        out.append(r)

    # 1. prospective 60 (scored 2026-11-06) and their tuned versions
    t60 = _texts(HS / "prospective" / "texts_60.jsonl")
    for u in json.loads((HS / "prospective" / "units_60.json").read_text()):
        add(id=f"{_prefix(u['source'])}:{u['id']}", source=u["source"], source_id=u["id"], kind="registry trial",
            author_kind="human", written_on=u.get("written_on"), T=t60.get(u["id"], {}).get("as_of", "2026-11-06"),
            sets=["prospective-60"], outcome=None, outcome_due=u.get("primary_completion"), parent=None, mode=None,
            text=t60.get(u["id"], {}).get("text"))
    for nct, p in json.loads((HS / "prospective" / "evolution_60.json").read_text())["pairs"].items():
        add(id=f"evo:ctgov:{nct}/tune/1", source="ours/evolution", source_id=f"{nct}/tune/1", kind="version",
            author_kind="model", written_on="2026-11-06", T="2026-11-06", sets=["prospective-60 versions"], outcome=None,
            parent=f"ctgov:{nct}", mode="tune", text=p.get("child_text"))
    # 2. calibration 74 (outcomes known)
    cal_t = {}
    for f in sorted(glob.glob(str(HS / "calibration" / "texts_*.jsonl"))):
        cal_t.update(_texts(Path(f)))
    for f in sorted(glob.glob(str(HS / "calibration" / "units_*.json"))):
        if "excluded" in f:
            continue
        for u in json.loads(Path(f).read_text()):
            t = cal_t.get(u["id"], {})
            add(id=f"{_prefix(u['source'])}:{u['id']}", source=u["source"], source_id=u["id"], kind="registry trial",
                author_kind="human", written_on=u.get("written_on"), T=t.get("as_of"), sets=["calibration-74"],
                outcome={"label": u.get("label"), "source": "units (registry results / publication)"}, parent=None, mode=None,
                text=t.get("text"), text_clean=t.get("b2_clean"))
    # 3. benchmark v2 (237, outcomes known)
    b2t = _texts(HS / "benchmark_v2_texts.jsonl")
    for u in json.loads((HA / "data" / "benchmark" / "v2_units.json").read_text())["units"]:
        t = b2t.get(u["id"], {})
        add(id=f"{_prefix(u['source'])}:{u['id']}", source=u["source"], source_id=u["id"], kind="registry trial",
            author_kind="human", written_on=u.get("written_on"), T=t.get("as_of"), sets=["benchmark-v2"],
            outcome={"label": u.get("label"), "outcome": u.get("outcome"), "document_date": u.get("first_outcome_document"),
                     "human_checked": u.get("human_checked")}, parent=None, mode=None, text=t.get("text"),
            text_clean=u.get("b2_clean"), edited_after_result=u.get("edited_after_result"))
    # 4. the wider prospective pool (ongoing trials, not scored except the 60)
    have = {r["id"] for r in out}
    for it in yaml.safe_load((HS / "prospective" / "pool.yaml").read_text())["items"]:
        rid = f"ctgov:{it['source_id']}"
        if rid in have:
            continue
        add(id=rid, source="ctgov", source_id=it["source_id"], kind="registry trial", author_kind="human",
            written_on=it.get("written_on"), T=None, sets=["prospective-pool-371"], outcome=None,
            outcome_due=it.get("primary_completion"), parent=None, mode=None,
            text="\n".join(x for x in [f"Title: {it.get('title', '')}", f"Summary: {it.get('brief_summary', '')}"] if x))
    # 5. Bio Arena export 2026-10-19
    ba = HA / "data" / "bioarena" / "2026-10-19" / "hypotheses.jsonl.gz"
    if ba.exists():
        for line in gzip.open(ba, "rt"):
            b = json.loads(line)
            h = b["hypothesis"]
            add(id=f"bioarena:{h['id']}", source="bioarena", source_id=h["id"], kind="submitted hypothesis",
                author_kind="AI agent" if "ИИ" in (h.get("author") or "") or "AI" in (h.get("author") or "") else "unknown",
                written_on=(h.get("createdAt") or "")[:10], T=None, sets=["bioarena-2026-10-19"], outcome=None, parent=None,
                mode=None, text=f"{h.get('title', '')}\n\n{h.get('description', '')}",
                source_scores={"rating": (b.get("ranking") or {}).get("rating"), "rank": (b.get("ranking") or {}).get("rank")})
    # 6. ChatGPT set
    ch = HA / "data" / "chatgpt_hypotheses.json"
    if ch.exists():
        d = json.loads(ch.read_text())
        for h in d["hypotheses"]:
            add(id=f"chatgpt:{h['id']}", source="chatgpt", source_id=str(h["id"]), kind="generated", author_kind="model",
                written_on=None, T=None, sets=["chatgpt-set"], outcome=None, parent=None, mode=None,
                text="\n".join(f"{k}: {h[k]}" for k in ("title", "claim", "known", "experiment", "prediction", "falsification") if h.get(k)))
    # 7. the outside reader's test pool (report of 2026-11-11): versions and generated hypotheses
    ap = KG / "reviews" / "argon-2026-11-12" / "report_pool_data.json"
    if ap.exists():
        pool = json.loads(ap.read_text())
        orig = {h["id"]: f"ctgov:{h['nct_id']}" for h in pool if h["mode"] == "original"}
        by_id = {r["id"]: r for r in out}
        mode_map = {"tune": "tune", "free": "free", "directed": "directed"}
        for h in pool:
            if h["mode"] == "original":
                r = by_id.get(orig[h["id"]])
                if r:
                    r["sets"].append("argon-test-2026-11-11")
                    r.setdefault("argon_label", h["id"])
                continue
            text = "\n".join(f"{k}: {v}" for k, v in (h.get("submitted_text") or {}).items())
            if h["mode"] in mode_map:
                parent = orig[h["parent_id"]]
                add(id=f"evo:{parent}/{mode_map[h['mode']]}/argon-2026-11-11", source="argon", source_id=h["id"], kind="version",
                    author_kind="model", written_on=h["cutoff_date"], T=h["cutoff_date"], sets=["argon-test-2026-11-11"],
                    outcome=None, parent=parent, mode=mode_map[h["mode"]], text=text, argon_label=h["id"])
            else:
                add(id=f"gen:argon-2026-11-11/{h['id']}", source="argon", source_id=h["id"], kind="generated",
                    author_kind="model", written_on=h["cutoff_date"], T=h["cutoff_date"], sets=["argon-test-2026-11-11"],
                    outcome=None, parent=None, mode=h["mode"], text=text, argon_label=h["id"])
    return out


def assign_short(rs: list[dict]) -> int:
    old = [json.loads(l) for l in (DB / "short_ids.jsonl").read_text().splitlines() if l.strip()]
    known = {o["id"]: o for o in old}
    # older versions were written as evo:<id>/tune/1 with the registry prefix inside; keep them as they are
    nums = [int(m.group(1)) for o in old if (m := re.fullmatch(r"H(\d+)", o["short"]))]
    nxt = max(nums) + 1
    used = {o["short"] for o in old}
    added = 0
    for r in rs:
        if r["id"] in known:
            r["short"] = known[r["id"]]["short"]
    scored_sets = {"benchmark-v2", "argon-test-2026-11-11"}
    for r in rs:
        if r["short"] or not scored_sets & set(r["sets"]):
            continue
        if r["kind"] == "version" and r["parent"]:
            ps = next((x["short"] for x in rs if x["id"] == r["parent"] and x["short"]), None)
            if not ps:
                continue
            base = ps + MODE_LETTER[r["mode"]]
            s, k = base, 1
            while s in used:
                k += 1
                s = f"{base}{k}"
        else:
            s = f"H{nxt:02d}"
            nxt += 1
        r["short"] = s
        used.add(s)
        old.append({"id": r["id"], "short": s, "pool": next(iter(scored_sets & set(r["sets"]))), "added": "2026-11-12"})
        added += 1
    (DB / "short_ids.jsonl").write_text("".join(json.dumps(o, ensure_ascii=False) + "\n" for o in old))
    return added


def usage(rs: list[dict]) -> None:
    """Where each registry trial appears: Argon packs (task or key files) and data files of hypothesis_sources."""
    by_reg = collections.defaultdict(list)
    for r in rs:
        if REG_ID.fullmatch(r["source_id"] or ""):
            by_reg[r["source_id"]].append(r)
    for f in sorted(glob.glob(str(KG / "reviews" / "**" / "*.json"), recursive=True)) + \
             sorted(glob.glob(str(HS / "**" / "*.json*"), recursive=True)) + sorted(glob.glob(str(HS / "**" / "*.yaml"), recursive=True)):
        try:
            ids = set(REG_ID.findall(Path(f).read_text(errors="ignore")))
        except OSError:
            continue
        rel = str(Path(f).relative_to(KG))
        for i in ids:
            for r in by_reg.get(i, []):
                r.setdefault("used_in", []).append(rel)


def build() -> dict:
    rs = rows()
    dup = [k for k, v in collections.Counter(r["id"] for r in rs).items() if v > 1]
    added = assign_short(rs)
    usage(rs)
    DB.mkdir(exist_ok=True)
    (DB / "rows.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rs))
    stats = {"rows": len(rs), "duplicate_ids": dup, "short_ids_added": added,
             "with_short": sum(1 for r in rs if r["short"]), "with_text": sum(1 for r in rs if r.get("text")),
             "with_outcome": sum(1 for r in rs if r.get("outcome")),
             "by_set": dict(collections.Counter(s for r in rs for s in r["sets"])),
             "by_kind": dict(collections.Counter(r["kind"] for r in rs))}
    return stats


if __name__ == "__main__":
    print(json.dumps({"build": build}[sys.argv[1] if len(sys.argv) > 1 else "build"](), indent=1, ensure_ascii=False))

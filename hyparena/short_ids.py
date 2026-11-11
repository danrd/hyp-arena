"""Short ids of hypotheses (H01, H02, ...; versions H49д, H49д2), kept in the hypothesis database.

User decision 2026-11-11: one numbering for every pool and source, with a leading zero (at least two digits), assigned
once and never renumbered. The registry is an append-only JSON-lines file in the private repository
(`longevity-kg/hypothesis_db/short_ids.jsonl`); the report reads it instead of computing ids in the page, so an id does
not move when a pool changes.

Row of the registry:
    {"id": "ctgov:NCT07726758", "short": "H49", "pool": "prospective-60", "added": "2026-11-11"}
    {"id": "evo:ctgov:NCT07726758/tune/1", "short": "H49д", "parent": "ctgov:NCT07726758", "mode": "tune", ...}

The stable id follows `specs/hypothesis-db-2026-11-09.yaml`: source prefix + source id (ctgov:NCT..., bioarena:<uuid>,
gen:<run>/<k>, evo:<parent>/<mode>/<k>).
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

KG = Path(os.environ.get("KG_DIR", "/home/user/longevity-kg"))
REGISTRY = KG / "hypothesis_db" / "short_ids.jsonl"

MODE_LETTER = {"tune": "д", "free": "с", "directed": "н"}
_REGISTRY_PREFIX = [("NCT", "ctgov"), ("ISRCTN", "isrctn"), ("UMIN", "umin"), ("NTR", "ntr"), ("DRKS", "drks"),
                    ("ACTRN", "anzctr")]
_SHORT = re.compile(r"^H(\d+)$")


def stable_id(source_id: str) -> str:
    """A registry trial id -> its stable database id (NCT07726758 -> ctgov:NCT07726758); other ids are kept as given."""
    if ":" in source_id:
        return source_id
    for pre, src in _REGISTRY_PREFIX:
        if source_id.startswith(pre):
            return f"{src}:{source_id}"
    raise ValueError(f"no source prefix for {source_id!r}: pass a stable id (source:id)")


def version_id(parent: str, mode: str, k: int = 1) -> str:
    return f"evo:{stable_id(parent)}/{mode}/{k}"


def fmt(n: int) -> str:
    return f"H{n:02d}"


def load(path: Path = REGISTRY) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def _check(rows: list[dict]) -> None:
    ids = [r["id"] for r in rows]
    shorts = [r["short"] for r in rows]
    if len(set(ids)) != len(ids) or len(set(shorts)) != len(shorts):
        raise ValueError("short id registry: duplicate id or short id")


def assign(rows: list[dict], ids: list[str], pool: str, date: str) -> list[dict]:
    """Give the next numbers to the original hypotheses not yet in the registry, in the order given. Returns new rows."""
    have = {r["id"] for r in rows}
    top = max((int(m.group(1)) for r in rows if (m := _SHORT.match(r["short"]))), default=0)
    new = []
    for i in ids:
        sid = stable_id(i)
        if sid in have:
            continue
        top += 1
        new.append({"id": sid, "short": fmt(top), "pool": pool, "added": date})
        have.add(sid)
    _check(rows + new)
    return new


def assign_version(rows: list[dict], parent: str, mode: str, date: str, pool: str = "") -> dict:
    """A new version of `parent` in `mode`: the parent's short id + the mode's letter, + a number from the second on."""
    p = stable_id(parent)
    by = {r["id"]: r for r in rows}
    if p not in by:
        raise KeyError(f"parent {p} has no short id")
    k = 1 + sum(1 for r in rows if r.get("parent") == p and r.get("mode") == mode)
    short = by[p]["short"] + MODE_LETTER.get(mode, "в") + ("" if k == 1 else str(k))
    row = {"id": version_id(p, mode, k), "short": short, "parent": p, "mode": mode, "pool": pool, "added": date}
    _check(rows + [row])
    return row


def append(rows: list[dict], path: Path = REGISTRY) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def for_report(results: list[dict], rows: list[dict]) -> dict[str, str]:
    """Report row id -> short id. Originals are registry ids (NCT...), versions are '<parent>+evo' / '+free' rows with
    `parent_id` and `evo_mode`; the k-th saved version of a parent in a mode is version k."""
    by = {r["id"]: r["short"] for r in rows}
    out, seen = {}, {}
    for r in results:
        try:
            if r.get("is_evolved"):
                key = (r["parent_id"], r.get("evo_mode") or "tune")
                seen[key] = seen.get(key, 0) + 1
                s = by.get(version_id(r["parent_id"], key[1], seen[key]))
            else:
                s = by.get(stable_id(r["id"]))
        except ValueError:
            s = None
        if s:
            out[r["id"]] = s
    return out

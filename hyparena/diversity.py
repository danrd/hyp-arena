"""A second kind of result next to the ranking: the top without relatives (2026-10-23).

The ranking itself is not changed. Hypotheses that are duplicates, variants (same core, another context) or analogs
(shared target and ATC class) of one another, or that descend from one another (evolution), form a family; the
list "top without relatives" takes the best-placed member of each family, in the order of the profile. It answers
"which different ideas lead", not "which single hypothesis leads"."""
from __future__ import annotations

from typing import Optional

FAMILY_TYPES = ("duplicate", "duplicate_approx", "variant", "analog")


def _relations(res: dict) -> list[dict]:
    """Typed relations of the result's cards, computed from the cards (their ids replaced by the item ids)."""
    from hyparena.card import proximity
    from hyparena.card.models import HypothesisCard
    cards = []
    for x in res["items"]:
        if x.get("card"):
            c = HypothesisCard.model_validate(x["card"])
            cards.append(c.model_copy(update={"id": x["id"]}))
    return [r.as_dict() for r in proximity.relations(cards, proximity.analog_keys, None)]


def families(res: dict, rels: Optional[list[dict]] = None) -> list[list[str]]:
    """Families of two or more items: connected groups of the relation types above plus parent links."""
    rels = _relations(res) if rels is None else rels
    ids = [x["id"] for x in res["items"]]
    known = set(ids)
    parent = {h: h for h in ids}

    def find(h):
        while parent[h] != h:
            parent[h] = parent[parent[h]]
            h = parent[h]
        return h

    edges = [(r["a"], r["b"]) for r in rels if set(r.get("types") or []) & set(FAMILY_TYPES)]
    edges += [(x["id"], x["parent"]) for x in res["items"] if x.get("parent")]
    for a, b in edges:
        if a in known and b in known:
            parent[find(a)] = find(b)
    groups: dict[str, list[str]] = {}
    for h in ids:
        groups.setdefault(find(h), []).append(h)
    return [g for g in groups.values() if len(g) > 1]


def top_distinct(res: dict, rels: Optional[list[dict]] = None) -> dict:
    """{"families": [[ids]], "profiles": {name: [{"id", "place", "hidden"}]}}: per profile, the best member of every
    family in profile order; `place` is its place in the full ranking, `hidden` the relatives it stands for that rank
    below it."""
    fam = families(res, rels)
    of = {h: i for i, g in enumerate(fam) for h in g}
    out = {}
    for name, r in (res.get("ranking") or {}).items():
        seen, rows = {}, []
        for place, h in enumerate(r["order"], 1):
            f = of.get(h)
            if f is not None and f in seen:
                seen[f]["hidden"].append(h)
                continue
            row = {"id": h, "place": place, "hidden": []}
            rows.append(row)
            if f is not None:
                seen[f] = row
        out[name] = rows
    return {"families": fam, "relation_types": list(FAMILY_TYPES), "profiles": out}

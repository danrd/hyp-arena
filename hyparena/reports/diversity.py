"""A second kind of result next to the ranking: the top without relatives (2026-10-23).

The ranking itself is not changed. Hypotheses that are duplicates, variants (same core, another context) or analogs
(shared target and ATC class) of one another, or that descend from one another (evolution), form a family; the
list "top without relatives" takes the best-placed member of each family, in the order of the profile. It answers
"which different ideas lead", not "which single hypothesis leads"."""
from __future__ import annotations

import re
from typing import Optional

FAMILY_TYPES = ("duplicate", "duplicate_approx", "variant", "analog")
MECHANISTIC_FAMILY_TYPES = ("duplicate", "duplicate_approx", "variant", "competitor", "analog", "analog_weak")

_ORGAN_BUCKETS = (
    ("skin_wound", ("wound", "re-epithelial", "keratinocyte", "epiderm", "dermis")),
    ("cerebral_microvessels", ("capillary", "small-vessel", "small vessel", "cadasil", "hyperemia", "arteriole")),
    ("bone_osteocyte", ("osteocyt", "osteoporos", "trabecular", "mineraliz", "sclerostin", "bone")),
    ("pancreatic_islets", ("islet", "pseudoislet", "beta-cell", "β-cell", "first-phase insulin", "insulin secretion")),
    ("cochlear_hair_cells", ("hair cell", "cochlea", "auditory", "cba/caj", "hearing")),
    ("cardiac_conduction", ("sinoatrial", "atrial fibrillation", "pacemaker", "re-entry")),
    ("skeletal_muscle", ("sarcopenia", "myoblast", "vastus lateralis", "quadriceps", "grip strength")),
    ("airway_mucus", ("copd", "bronchial", "mucociliary", "cftr")),
    ("lens", ("cataract", "lens", "eye-bank")),
    ("hippocampus", ("hippocamp", "alzheimer", "ca1", "astrocyt")),
)

_TARGET_TOKENS = (
    "kir21", "pip2", "cx43", "connexin43", "cx36", "connexin36", "cx46", "cx50",
    "piezo1", "hcn4", "cftr", "kcnq4", "katp", "kir62", "clc1", "bkchannel",
    "electricfield", "woundfield", "dynamicclamp",
)


def _card_organ_and_targets(card) -> tuple[set[str], set[str]]:
    chunks = [
        card.claim_plain or "",
        card.pico.population.label or "",
        card.pico.population.condition or "",
        card.pico.outcome.metric or "",
        card.decisive_experiment.span or "",
        *[i.label for i in card.pico.intervention],
        *[f"{c.subject.label} {c.object.label}" for c in card.claims],
    ]
    raw = " ".join(chunks).lower()
    compact = re.sub(r"[^a-z0-9]+", "", raw)
    organs = {name for name, kws in _ORGAN_BUCKETS if any(kw in raw for kw in kws)}
    targets = {tok for tok in _TARGET_TOKENS if tok in compact}
    if "connexin43" in targets:
        targets.add("cx43")
    if "connexin36" in targets:
        targets.add("cx36")
    if "wound" in raw and "field" in raw:
        targets.add("woundfield")
    return organs, targets


def _relations(res: dict) -> list[dict]:
    """Typed relations of the result's cards, computed from the cards (their ids replaced by the item ids)."""
    from hyparena.novelty import proximity
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


def pool_clusters(
    cards_by_id: dict,
    ranks_by_profile: Optional[dict[str, list[str]]] = None,
) -> dict:
    """Offline cluster deduplication across a pool of `HypothesisCard`s (no network calls).

    Groups hypotheses into connected families when `proximity.relations` finds `duplicate`, `variant`,
    `competitor`, `analog`, or `analog_weak`, OR when two hypotheses target the same organ/clinical-syndrome
    bucket AND share either a canonical bioelectric/molecular lever or both target the same micro-domain
    (e.g. ex vivo wound electric field, pancreatic islet electrical coupling, cochlear hair-cell conductance).
    Returns `clusters` (families of size >= 2), `cluster_of` (`hid -> cluster_id`), and `top_distinct` per profile.
    """
    from hyparena.novelty import proximity

    ids = list(cards_by_id.keys())
    if not ids:
        return {"clusters": [], "cluster_of": {}, "top_distinct": {}}

    cards = [cards_by_id[h].model_copy(update={"id": h}) for h in ids]
    prox_rels = [r.as_dict() for r in proximity.relations(cards, None, None)]

    parent = {h: h for h in ids}

    def find(h: str) -> str:
        while parent[h] != h:
            parent[h] = parent[parent[h]]
            h = parent[h]
        return h

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            if ids.index(ra) < ids.index(rb):
                parent[rb] = ra
            else:
                parent[ra] = rb

    for r in prox_rels:
        if set(r.get("types") or []) & set(MECHANISTIC_FAMILY_TYPES):
            if r["a"] in parent and r["b"] in parent:
                union(r["a"], r["b"])

    meta = {h: _card_organ_and_targets(cards_by_id[h]) for h in ids}
    micro_domains = {"skin_wound", "pancreatic_islets", "cochlear_hair_cells"}
    for i, a in enumerate(ids):
        org_a, tgt_a = meta[a]
        for b in ids[i + 1 :]:
            org_b, tgt_b = meta[b]
            shared_org = org_a & org_b
            if not shared_org:
                continue
            if (tgt_a & tgt_b) or (shared_org & micro_domains):
                union(a, b)

    grouped: dict[str, list[str]] = {}
    for h in ids:
        grouped.setdefault(find(h), []).append(h)

    multi = [members for members in grouped.values() if len(members) > 1]
    clusters = []
    cluster_of: dict[str, str] = {}
    peers_of: dict[str, list[str]] = {}
    for idx, members in enumerate(multi, 1):
        cid = f"C{idx:02d}"
        shared_org = set.intersection(*(meta[m][0] for m in members)) if members else set()
        shared_tgt = set.intersection(*(meta[m][1] for m in members)) if members else set()
        label = ", ".join(sorted(shared_org | shared_tgt)) or "related_mechanism"
        clusters.append({"cluster_id": cid, "label": label, "members": members})
        for m in members:
            cluster_of[m] = cid
            peers_of[m] = [x for x in members if x != m]

    distinct_by_prof: dict[str, list[dict]] = {}
    for prof, order in (ranks_by_profile or {}).items():
        seen_c: dict[str, dict] = {}
        prof_rows: list[dict] = []
        for place, h in enumerate(order, 1):
            cid = cluster_of.get(h)
            if cid and cid in seen_c:
                seen_c[cid]["hidden_relatives"].append(h)
                continue
            entry = {"id": h, "place": place, "cluster_id": cid, "hidden_relatives": []}
            prof_rows.append(entry)
            if cid:
                seen_c[cid] = entry
        distinct_by_prof[prof] = prof_rows

    return {
        "clusters": clusters,
        "cluster_of": cluster_of,
        "peers_of": peers_of,
        "top_distinct": distinct_by_prof,
    }

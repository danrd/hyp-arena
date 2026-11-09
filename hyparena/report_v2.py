"""Pool report, second layout (user decision 2026-11-07: take the outside reader's (Argon's) report as the base and correct it
towards the method: Russian names instead of codes, every evolution pair, a fuller help).

    python -m hyparena.report_v2 prospective [--n 60] [--out FILE]

The numbers come from hyparena.report_html.build (the same rules, ASPID and improvement list); this module only reshapes them
into one JSON object that the page template (hyparena/templates/pool_report_v2.html) renders in the browser. The template
uses Tailwind from its CDN (version pinned) and has no other dependency.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Optional

from hyparena import report_html as rh
from hyparena.card import aspid_v3
from hyparena.card import rules_v32 as r32

TEMPLATE = Path(__file__).resolve().parent / "templates" / "pool_report_v2.html"

PROFILE_LABEL = {"evidence": "Доказательность", "funding": "Финансирование", "frontier": "Фронтир"}
PROFILE_ABOUT = {
    "evidence": "Насколько механизм обоснован литературой сейчас: баланс доказательств (опровергнуто / неизвестно / подтверждено), затем что даст эксперимент, затем размах.",
    "funding": "Готовность к финансированию: баланс доказательств, реализуемость, затем рост внимания, роль ИИ и новизна, затем информативность и размах.",
    "frontier": "Поисковые программы (ARPA-H, Foresight, ранние R&D): новизна первой, затем баланс доказательств, затем что даст эксперимент, его цена и размах.",
}


def _ind_name(k: str) -> str:
    return rh.IND_NAMES.get(k, (k, k))[0]


def _order_text(tiers: list[list[str]]) -> str:
    return " > ".join("{" + ", ".join(_ind_name(k) for k in t) + "}" if len(t) > 1 else _ind_name(t[0]) for t in tiers)


def _expected_text(i: dict) -> str:
    ex = i.get("expected")
    if not ex:
        return "ожидаемый эффект заранее не считается"
    names = {"chain_state": "баланс доказательств", "I": "I", "support_share": "подтверждённость", "endpoint_clinical": "конечная точка", "N": "новизна"}
    def v(k, x):
        if k == "endpoint_clinical":
            return rh.ENDPOINT_NAMES.get(x, (str(x),))[0]
        if k == "N":
            return rh.NOVELTY_NAMES.get(x, rh.NOVELTY_NAMES[None])[0]
        return rh.fmt(x)
    ind = ", ".join(f"{names.get(k, k)} {v(k, a)} → {v(k, b)}" for k, (a, b) in ex["indicators"].items())
    sc = " · ".join(f"{PROFILE_LABEL.get(p, p)} {b - a:+.3f}" for p, (a, b) in ex["score"].items() if p in PROFILE_LABEL)
    return (ind + "; " if ind else "") + "оценка: " + sc


def _link(c: dict, levels: dict) -> dict:
    R = r32.non_refutation(c["F"], c["A"])
    return {"id": c["id"], "type": c["link"], "claim": c["text"], "hallmark": c.get("hallmark"), "F": c["F"], "A": c["A"],
            "S": c["S"], "ci": [c["lo"], c["hi"]], "R": round(R, 4), "checked": c.get("checked", True),
            "in_P": c.get("in_P", True), "primary": c.get("primary", False), "parallel": c.get("parallel_outcome", False),
            "novelty": levels.get(c["id"]),
            "records": [{"pmid": r["pmid"], "side": r["side"], "design": r["design"], "n": r["n"], "effect": r["effect"],
                         "w": r["w"], "f": r.get("f"), "quote": r["quote"]} for r in c["records"]]}


def data(rep: dict) -> dict:
    H, m = rep["hyps"], rep["meta"]
    profiles = aspid_v3.load()
    evo = rep.get("evolution") or {}
    drift_of = {}
    for u, p in evo.items():
        child = u if u.endswith(rh.EVO_SUFFIXES["free"]) else u + rh.EVO_SUFFIXES[p.get("mode", "tune")]
        if p.get("compare"):
            drift_of[child] = {**(p["compare"].get("drift") or {}), "mode": p.get("mode", "tune"), "applied": p.get("applied", []),
                               "changes": p.get("changes", []), "child_text": p.get("child_text", ""),
                               "cited": p.get("cited_pmids"), "cited_found": p.get("cited_found"), "distance": p.get("distance"),
                               "attempts": p.get("attempts"), "constraint_kept": p.get("constraint_kept")}
    n_ranked = {p: len(rep["ranks"][p]) for p in profiles}
    results, pubmed = [], {}
    for h, x in H.items():
        base = {"id": h, "title": x.get("title") or h, "type": x.get("type"), "type_ru": rh.TYPE_NAMES.get(x.get("type"), (x.get("type") or "—",))[0],
                "is_evolved": bool(x.get("parent")), "parent_id": x.get("parent"), "evo_mode": x.get("evo_mode"),
                "new_after": x.get("new_after"), "outcome": x.get("outcome"), "scored": x.get("P") is not None and x.get("gate") == "pass"}
        if not base["scored"]:
            results.append(base)
            continue
        v = x.get("values") or {}
        levels = x.get("link_levels") or {}
        lifts = sorted({i for p in profiles for i, _ in x["contrib"][p]["up"]})
        lowers = sorted({i for p in profiles for i, _ in x["contrib"][p]["down"]})
        room = x.get("room") or {}
        base.update({
            "plain": x.get("plain"), "P": x["P"], "support_share": x.get("support_share"), "chain_state": v.get("chain_state"), "N": x.get("N"), "N_pmid": x.get("N_pmid"),
            "I": x["I"], "I_headroom": v.get("I_headroom"), "W": x["scope"], "feasibility": v.get("feasibility"),
            "endpoint": x.get("endpoint_clinical"), "ai_role": x.get("ai_role") or "none", "trend": x.get("trend_pubmed"),
            "best_design": v.get("best_design_outcome"), "independent": v.get("independent_outcome"), "flags": flag_details(x),
            "experiment": x.get("experiment"), "completion": x.get("completion"),
            "links": [_link(c, levels) for c in x["chain"]],
            "alternatives": x.get("alternatives", []),
            "lifts": [f"{_ind_name(i)} (лучше, чем у {round((x['pct'].get(i) or 0) * 100)}% пула)" for i in lifts],
            "lowers": [f"{_ind_name(i)} (лучше, чем у {round((x['pct'].get(i) or 0) * 100)}% пула)" for i in lowers],
            "improvements": [{"cls": i["cls"], "what": i["what"][0], "expected": _expected_text(i),
                              "facts": [f"PMID {f['pmid']} ({'за' if f['side'] == 'for' else 'против'})" for f in i.get("facts", [])]}
                             for i in x.get("improvements") or []],
            "room": {p: round(b - a, 4) for p, (a, b) in (room.get("score") or {}).items()},
            "room_N": room.get("N"), "room_not_computed": bool(room.get("not_computed")),
            "aspid": {p: {"score": x["aspid"].get(p), "place": x["rank"].get(p), "of": n_ranked[p], "p_top5": x["p_top5"].get(p)}
                      for p in profiles},
            "drift": drift_of.get(h),
        })
        results.append(base)
        for c in x["chain"]:
            for r in c["records"]:
                e = pubmed.setdefault(r["pmid"], {"pmid": r["pmid"], "design": r["design"], "n": r["n"], "quote": r["quote"],
                                                  "used_in": [], "sides": set()})
                if h not in e["used_in"]:
                    e["used_in"].append(h)
                e["sides"].add(r["side"])
    for e in pubmed.values():
        e["sides"] = sorted(e["sides"])
    hidden = ("P", "R")       # non-refutation left the profiles in v3.5 and the report in v3.7 (user 2026-11-09)
    names = {**rh.IND_NAMES, **rh.GLOSSARY_NAMES}
    glossary = [{"term": names.get(k, (k, k))[0], "text": rh.t_ru(v)} for k, v in {**rh.TIPS, **rh.GLOSSARY_EXTRA}.items() if k not in hidden]
    return {
        "meta": {"title": m["title_ru"], "about": m["about_ru"], "date": m["date"], "method": m["method"], "sha": m["sha"],
                 "n": m["n"], "n_scored": m["n_scored"], "outcomes": m["outcomes"]},
        "profiles": [{"key": p, "label": PROFILE_LABEL.get(p, p), "about": PROFILE_ABOUT.get(p, ""), "order": _order_text(prof.tiers),
                      "tiers": [[_ind_name(k) for k in t] for t in prof.tiers]}
                     for p, (prof, _) in profiles.items()],
        "names": {"novelty": {k or "": v[0] for k, v in rh.NOVELTY_NAMES.items()}, "scope": {k: v[0] for k, v in rh.SCOPE_NAMES.items()},
                  "endpoint": {(k or ""): v[0] for k, v in rh.ENDPOINT_NAMES.items()}, "ai": {k: v[0] for k, v in rh.AI_NAMES.items()},
                  "link": {k: v[0] for k, v in rh.LINK_NAMES.items()}, "design": {k: v[0] for k, v in rh.DESIGN_NAMES.items()},
                  "disc": {k: v[0] for k, v in rh.DISC.items()}, "flags": {k: v[0] for k, v in FLAG_NAMES.items()}},
        "tips": {k: rh.t_ru(v) for k, v in {**rh.TIPS, **rh.GLOSSARY_EXTRA}.items() if k not in hidden},
        "results": results, "pubmed": sorted(pubmed.values(), key=lambda e: e["pmid"]), "glossary": glossary,
    }


def flag_details(x: dict) -> list[dict]:
    """Each flag of a hypothesis with the concrete reason in this hypothesis (user request 2026-11-08: not the general idea of
    the flag)."""
    chain = {c["id"]: c for c in x.get("chain", [])}
    out = []
    for fl in x.get("flags", []):
        code, detail = fl, ""
        if fl == "build_mechanism":
            detail = ("В цепочке только исход: мишень, путь и промежуточный эффект не выписаны, поэтому механизм не проверялся; "
                      "оценка держится на одном звене «" + (next(iter(chain.values()))["text"] if chain else "") + "».")
        elif fl == "contested_link":
            bad = [c for c in chain.values() if c["A"] > 0 and c["A"] >= c["F"] / 2]
            detail = "; ".join(f"звено «{c['text']}»: вес «за» {c['F']:.2f}, «против» {c['A']:.2f} (против: " +
                               ", ".join("PMID " + r["pmid"] for r in c["records"] if r["side"] == "against") + ")" for c in bad)
        elif fl == "improve_experiment":
            open_ = [a for a in x.get("alternatives", []) if a["support"] > 0 and "eliminated" not in (a["on_positive"], a["on_negative"])]
            detail = ("Эксперимент не отсекает подкреплённые альтернативы: " + "; ".join(
                f"«{a['text']}» (опора {a['support']:.2f}; при успехе — {rh.DISC.get(a['on_positive'], (a['on_positive'],))[0]}, "
                f"при неудаче — {rh.DISC.get(a['on_negative'], (a['on_negative'],))[0]})" for a in open_) +
                f". Если отсекать их все, I выросла бы с {x['I']:.2f} до {(x.get('values') or {}).get('I_headroom') or x['I']:.2f}.")
        elif fl == "name_supported_alternatives":
            n = len(x.get("alternatives", []))
            detail = (f"Ни у одной из {n} предложенных альтернатив нет опоры в литературе до даты среза, поэтому эксперимент "
                      "ничего не отсекает и I равна нижней границе.") if n else "Альтернативные объяснения не предложены."
        elif fl == "find_primary_report":
            recs = [r for c in chain.values() for r in c["records"] if r.get("trial") and not r.get("primary")]
            detail = "; ".join(f"обзор PMID {r['pmid']} пересказывает испытание «{r['trial']}», статья самого испытания не найдена" for r in recs) \
                or "Обзор пересказывает испытание, статья самого испытания не найдена."
        elif fl == "retracted_source_dropped":
            detail = "Среди найденных статей была отозванная; она исключена и веса не получила."
        elif fl.endswith("_established_by_approval"):
            cid = fl[: -len("_established_by_approval")]
            c = chain.get(cid)
            code = "established_by_approval"
            detail = (f"Звено «{c['text']}» принято как умеренно подтверждённое без поиска: вещество одобрено (ChEMBL, фаза 4) "
                      "и действует на названную в звене мишень.") if c else ""
        out.append({"code": code, "name": FLAG_NAMES.get(code, (code,))[0], "detail": detail})
    return out


FLAG_NAMES = {
    "build_mechanism": ("механизм не выписан", ""), "name_supported_alternatives": ("нет подкреплённых альтернатив", ""),
    "improve_experiment": ("эксперимент оставляет альтернативы", ""), "find_primary_report": ("найти статью самого испытания", ""),
    "contested_link": ("спорное звено", ""), "retracted_source_dropped": ("отозванная статья исключена", ""),
    "established_by_approval": ("звено принято по одобрению", ""),
}


def render(rep: dict) -> str:
    d = data(rep)
    body = json.dumps(d, ensure_ascii=False, default=str).replace("</", "<\\/")
    return TEMPLATE.read_text(encoding="utf-8").replace("__DATA__", body).replace("__TITLE__", rh.e(d["meta"]["title"]))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pool", choices=["prospective"])
    ap.add_argument("--n", type=int, default=60)
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    rep, default = rh.prospective(a.n)
    out = Path(a.out or default.replace(".html", "_v2.html"))
    out.write_text(render(rep), encoding="utf-8")
    print(out, round(out.stat().st_size / 1024), "KB")


if __name__ == "__main__":
    main()
